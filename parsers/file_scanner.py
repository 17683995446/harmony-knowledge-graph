"""
File Scanner - 文件扫描器
扫描项目目录，识别ArkTS文件，计算文件哈希用于增量更新
"""

import os
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
import pathspec

from core.logger_manager import get_logger

logger = get_logger("file_scanner")


@dataclass
class FileInfo:
    """文件信息数据类"""
    path: str
    relative_path: str
    size: int
    modified_time: float
    content_hash: str
    is_new: bool = True
    is_modified: bool = False
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "size": self.size,
            "modified_time": self.modified_time,
            "content_hash": self.content_hash,
            "is_new": self.is_new,
            "is_modified": self.is_modified
        }


class FileScanner:
    """文件扫描器类"""
    
    # ArkTS文件扩展名
    ARKTS_EXTENSIONS = {".ets", ".ts"}
    
    # 默认忽略模式
    DEFAULT_IGNORE_PATTERNS = [
        "node_modules/",
        "build/",
        "dist/",
        ".git/",
        ".idea/",
        ".vscode/",
        "*.min.js",
        "*.min.css",
        "*.d.ts",
        "hvigor/",
        "oh_modules/",
        ".preview/",
    ]
    
    def __init__(
        self,
        project_path: str,
        ignore_patterns: Optional[List[str]] = None,
        max_workers: int = 8
    ):
        self.project_path = Path(project_path).resolve()
        self.max_workers = max_workers
        
        # 合并忽略模式
        patterns = self.DEFAULT_IGNORE_PATTERNS.copy()
        if ignore_patterns:
            patterns.extend(ignore_patterns)
        
        self.ignore_spec = pathspec.PathSpec.from_lines(
            pathspec.patterns.GitWildMatchPattern,
            patterns
        )
        
        logger.info(f"初始化文件扫描器: {self.project_path}")
    
    def scan(self) -> List[FileInfo]:
        """
        扫描项目目录，返回所有ArkTS文件信息
        
        Returns:
            List[FileInfo]: 文件信息列表
        """
        logger.info("开始扫描项目文件...")
        
        # 收集所有文件路径
        file_paths = self._collect_file_paths()
        logger.info(f"发现 {len(file_paths)} 个潜在文件")
        
        # 并行处理文件
        file_infos = self._process_files_parallel(file_paths)
        
        logger.info(f"扫描完成，共 {len(file_infos)} 个ArkTS文件")
        return file_infos
    
    def scan_incremental(
        self,
        existing_files: Dict[str, str]
    ) -> tuple[List[FileInfo], List[str]]:
        """
        增量扫描，只返回变更的文件
        
        Args:
            existing_files: 已存在的文件路径到哈希的映射
            
        Returns:
            (变更的文件列表, 删除的文件路径列表)
        """
        logger.info("开始增量扫描...")
        
        current_files = self.scan()
        current_paths = {f.relative_path for f in current_files}
        existing_paths = set(existing_files.keys())
        
        # 找出变更的文件
        changed_files = []
        for file_info in current_files:
            if file_info.relative_path not in existing_files:
                # 新文件
                file_info.is_new = True
                changed_files.append(file_info)
            elif existing_files[file_info.relative_path] != file_info.content_hash:
                # 修改过的文件
                file_info.is_modified = True
                changed_files.append(file_info)
        
        # 找出删除的文件
        deleted_files = list(existing_paths - current_paths)
        
        logger.info(f"增量扫描完成: {len(changed_files)} 个变更, {len(deleted_files)} 个删除")
        return changed_files, deleted_files
    
    def _collect_file_paths(self) -> List[Path]:
        """收集所有文件路径"""
        file_paths = []
        
        for root, dirs, files in os.walk(self.project_path):
            root_path = Path(root)
            try:
                relative_root = root_path.relative_to(self.project_path)
            except ValueError:
                logger.warning(f"跳过项目目录外的路径: {root_path}")
                dirs[:] = []
                continue
            
            # 过滤目录
            dirs[:] = [
                d for d in dirs
                if not self.ignore_spec.match_file(str(relative_root / d))
            ]
            
            for filename in files:
                file_path = root_path / filename
                try:
                    relative_path = file_path.relative_to(self.project_path)
                except ValueError:
                    logger.warning(f"跳过项目目录外的文件: {file_path}")
                    continue
                
                # 检查是否应该忽略
                if self.ignore_spec.match_file(str(relative_path)):
                    continue
                
                # 检查是否是ArkTS文件
                if file_path.suffix in self.ARKTS_EXTENSIONS:
                    file_paths.append(file_path)
        
        return file_paths
    
    def _process_files_parallel(self, file_paths: List[Path]) -> List[FileInfo]:
        """并行处理文件"""
        file_infos = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_single_file, path): path
                for path in file_paths
            }
            
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    file_info = future.result()
                    if file_info:
                        file_infos.append(file_info)
                except Exception as e:
                    logger.error(f"处理文件失败 {path}: {e}")
        
        # 按路径排序，保证一致性
        file_infos.sort(key=lambda x: x.relative_path)
        return file_infos
    
    def _process_single_file(self, file_path: Path) -> Optional[FileInfo]:
        """处理单个文件"""
        try:
            stat = file_path.stat()
            content_hash = self._calculate_file_hash(file_path)
            
            return FileInfo(
                path=str(file_path),
                relative_path=str(file_path.relative_to(self.project_path)),
                size=stat.st_size,
                modified_time=stat.st_mtime,
                content_hash=content_hash
            )
        except Exception as e:
            logger.error(f"处理文件失败 {file_path}: {e}")
            return None
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件内容哈希"""
        hasher = hashlib.blake2b(digest_size=16)
        
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        
        return hasher.hexdigest()
