"""
Pipeline Manager - 流水线管理器
协调整个代码分析流程：扫描、解析、存储
"""

import os
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from core.config_manager import get_configuration
from core.logger_manager import get_logger
from core.parallel_processor import ParallelProcessor, BatchInserter
from parsers.file_scanner import FileScanner, FileInfo
from parsers.arkts_parser import ArkTSParser, ParseResult
from parsers.ast_analyzer import ASTAnalyzer
from database.connection_pool import get_database_manager
from database.entity_repository import EntityRepository
from database.relation_repository import RelationRepository

logger = get_logger("pipeline_manager")


@dataclass
class PipelineResult:
    """流水线结果"""
    success: bool
    scanned_files: int = 0
    parsed_entities: int = 0
    found_relations: int = 0
    duration: float = 0.0
    error: Optional[str] = None
    stages: Dict[str, Any] = field(default_factory=dict)


class PipelineManager:
    """流水线管理器类"""

    def __init__(
        self,
        project_path: str,
        max_workers: Optional[int] = None,
        batch_size: int = 1000
    ):
        self.project_path = Path(project_path).resolve()
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.config = get_configuration()

        # 初始化组件
        self.file_scanner = FileScanner(
            project_path=str(self.project_path),
            max_workers=max_workers or self.config.parser_max_workers
        )
        self.arkts_parser = ArkTSParser()
        self.ast_analyzer = ASTAnalyzer()

        # 数据库组件
        self.entity_repo = EntityRepository()
        self.relation_repo = RelationRepository()

    def run_full_pipeline(self, incremental: bool = True) -> PipelineResult:
        """
        运行完整流水线

        Args:
            incremental: 是否使用增量扫描

        Returns:
            PipelineResult: 流水线执行结果
        """
        start_time = time.time()

        try:
            # 阶段1: 扫描文件
            logger.info("阶段1: 扫描文件...")
            file_infos = self._scan_files(incremental)

            if not file_infos:
                logger.info("没有需要处理的文件")
                return PipelineResult(
                    success=True,
                    scanned_files=0,
                    duration=time.time() - start_time
                )

            # 阶段2: 解析代码
            logger.info("阶段2: 解析代码...")
            parse_results = self._parse_files(file_infos)

            # 阶段3: 分析AST
            logger.info("阶段3: 分析AST...")
            analysis_result = self._analyze_ast(parse_results)

            # 阶段4: 存储到数据库
            logger.info("阶段4: 存储到数据库...")
            storage_stats = self._store_to_database(file_infos, parse_results)

            duration = time.time() - start_time

            logger.info(f"流水线完成! 耗时: {duration:.2f}秒")

            return PipelineResult(
                success=True,
                scanned_files=len(file_infos),
                parsed_entities=storage_stats.get("entities", 0),
                found_relations=storage_stats.get("relations", 0),
                duration=duration,
                stages={
                    "files_scanned": len(file_infos),
                    "entities_parsed": sum(len(r.entities) for r in parse_results),
                    "analysis": analysis_result
                }
            )

        except Exception as e:
            logger.error(f"流水线执行失败: {e}", exc_info=True)
            return PipelineResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time
            )

    def _scan_files(self, incremental: bool) -> List[FileInfo]:
        """扫描文件"""
        if incremental:
            # 获取已存在的文件哈希
            existing_files = self._get_existing_file_hashes()
            file_infos, deleted_files = self.file_scanner.scan_incremental(existing_files)

            # 删除已不存在的文件记录
            for file_path in deleted_files:
                self._delete_file_data(file_path)

            return file_infos
        else:
            return self.file_scanner.scan()

    def _get_existing_file_hashes(self) -> Dict[str, str]:
        """获取已存在的文件哈希"""
        from database.connection_pool import get_database_manager

        db_manager = get_database_manager()
        rows = db_manager.fetch_all("SELECT path, hash FROM files")

        return {row["path"]: row["hash"] for row in rows if row["hash"]}

    def _delete_file_data(self, file_path: str) -> None:
        """删除文件相关数据"""
        from database.connection_pool import get_database_manager

        db_manager = get_database_manager()

        # 获取文件ID
        row = db_manager.fetch_one("SELECT id FROM files WHERE path = ?", (file_path,))
        if row:
            file_id = row["id"]

            # 删除关系
            self.relation_repo.delete_relations_by_file(file_id)

            # 删除实体
            self.entity_repo.delete_entities_by_file(file_id)

            # 删除文件记录
            db_manager.execute_write("DELETE FROM files WHERE id = ?", (file_id,))

            logger.debug(f"删除文件数据: {file_path}")

    def _parse_files(self, file_infos: List[FileInfo]) -> List[ParseResult]:
        """解析文件"""
        file_paths = [f.path for f in file_infos]

        # 使用并行处理器
        processor = ParallelProcessor(
            max_workers=self.max_workers,
            chunk_size=100,
            show_progress=True
        )

        def parse_single_file(file_path: str) -> ParseResult:
            return self.arkts_parser.parse_file(file_path)

        results = processor.process_items(file_paths, parse_single_file)

        # 提取成功的结果
        parse_results = []
        for result in results:
            if result.success and result.data:
                parse_results.append(result.data)

        logger.info(f"解析完成: {len(parse_results)}/{len(file_paths)} 个文件")

        return parse_results

    def _analyze_ast(self, parse_results: List[ParseResult]) -> Dict:
        """分析AST"""
        return self.ast_analyzer.analyze_results(parse_results)

    def _store_to_database(
        self,
        file_infos: List[FileInfo],
        parse_results: List[ParseResult]
    ) -> Dict[str, int]:
        """存储到数据库"""
        stats = {"files": 0, "entities": 0, "relations": 0}

        # 存储文件信息
        self._store_files(file_infos)
        stats["files"] = len(file_infos)

        # 存储实体
        entity_count = self._store_entities(parse_results)
        stats["entities"] = entity_count

        # 存储关系
        relation_count = self._store_relations(parse_results)
        stats["relations"] = relation_count

        return stats

    def _store_files(self, file_infos: List[FileInfo]) -> None:
        """存储文件信息（线程安全）"""
        from database.connection_pool import get_database_manager
        import threading

        db_manager = get_database_manager()
        
        # 使用线程锁确保并发安全
        if not hasattr(self, '_file_store_lock'):
            self._file_store_lock = threading.Lock()

        with self._file_store_lock:
            for file_info in file_infos:
                # 使用INSERT OR REPLACE避免并发冲突
                db_manager.execute_write(
                    """
                    INSERT OR REPLACE INTO files (path, hash, size, modified_time, parsed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        file_info.relative_path,
                        file_info.content_hash,
                        file_info.size,
                        file_info.modified_time,
                        time.time()
                    )
                )

    def _resolve_relative_path(self, file_path: str) -> str:
        """将绝对文件路径转换为项目相对路径"""
        prefix = str(self.project_path) + os.sep
        if file_path.startswith(prefix):
            return file_path[len(prefix):]
        return file_path

    def _store_entities(self, parse_results: List[ParseResult]) -> int:
        """存储实体（带事务保证原子性）"""
        from database.connection_pool import get_database_manager

        db_manager = get_database_manager()
        total_entities = 0

        for result in parse_results:
            # 获取文件ID
            relative_path = self._resolve_relative_path(result.file_path)
            file_row = db_manager.fetch_one(
                "SELECT id FROM files WHERE path = ?",
                (relative_path,)
            )

            if not file_row:
                continue

            file_id = file_row["id"]

            # 使用显式事务包裹删除+插入操作，保证原子性
            with db_manager.get_pool().connection() as conn:
                try:
                    # 开始事务
                    conn.execute("BEGIN")
                    
                    # 删除旧实体及相关数据
                    conn.execute(
                        "DELETE FROM method_params WHERE method_id IN (SELECT id FROM entities WHERE file_id = ?)",
                        (file_id,)
                    )
                    conn.execute(
                        "DELETE FROM decorators WHERE entity_id IN (SELECT id FROM entities WHERE file_id = ?)",
                        (file_id,)
                    )
                    conn.execute("DELETE FROM entities WHERE file_id = ?", (file_id,))
                    
                    # 准备并插入新实体
                    entities_to_insert = []
                    for entity in result.entities:
                        entities_to_insert.append((entity, file_id))
                    
                    if entities_to_insert:
                        # 确保名称存在
                        all_names = set()
                        for entity, _ in entities_to_insert:
                            all_names.add(entity.name)
                            if entity.extends:
                                all_names.add(entity.extends)
                            if entity.implements:
                                all_names.update(entity.implements)
                            for call in entity.calls:
                                all_names.add(call)
                        
                        for name in all_names:
                            if name:
                                conn.execute(
                                    "INSERT OR IGNORE INTO names (name, hash) VALUES (?, ?)",
                                    (name, 0)
                                )
                        
                        # 插入实体
                        for entity, fid in entities_to_insert:
                            name_row = conn.execute("SELECT id FROM names WHERE name = ?", (entity.name,)).fetchone()
                            type_row = conn.execute("SELECT id FROM entity_types WHERE name = ?", (entity.entity_type.value,)).fetchone()
                            
                            if name_row and type_row:
                                cursor = conn.execute(
                                    """INSERT INTO entities 
                                        (name_id, type_id, file_id, line_start, line_end, column_start, column_end, documentation)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                    (name_row[0], type_row[0], fid, entity.location.line,
                                     entity.location.end_line or entity.location.line,
                                     entity.location.column, entity.location.end_column or entity.location.column,
                                     entity.documentation)
                                )
                                total_entities += 1
                    
                    # 提交事务
                    conn.commit()
                    
                except Exception as e:
                    # 回滚事务
                    conn.rollback()
                    logger.error(f"存储实体失败，已回滚: {e}")
                    raise

        return total_entities

    def _store_relations(self, parse_results: List[ParseResult]) -> int:
        """存储关系"""
        from database.connection_pool import get_database_manager

        db_manager = get_database_manager()
        total_relations = 0

        # 构建名称 -> 实体ID 的查找字典（用于调用关系和继承关系）
        name_to_entity_id: Dict[str, int] = {}
        entity_rows = db_manager.fetch_all(
            """
            SELECT e.id, n.name
            FROM entities e
            JOIN names n ON e.name_id = n.id
            """
        )
        for row in entity_rows:
            name_to_entity_id[row["name"]] = row["id"]

        # 构建文件路径 -> 文件ID 的查找字典（用于导入关系）
        path_to_file_id: Dict[str, int] = {}
        file_rows = db_manager.fetch_all("SELECT id, path FROM files")
        for row in file_rows:
            path_to_file_id[row["path"]] = row["id"]

        # 收集所有调用关系，用于批量插入
        call_relations_batch: List[tuple] = []

        for result in parse_results:
            # 获取当前文件的文件ID
            relative_path = self._resolve_relative_path(result.file_path)
            file_id = path_to_file_id.get(relative_path)
            if not file_id:
                logger.warning(f"未找到文件记录，跳过关系存储: {relative_path}")
                continue

            for entity in result.entities:
                # 查找当前实体在数据库中的ID
                entity_id = name_to_entity_id.get(entity.name)
                if not entity_id:
                    logger.debug(f"未找到实体 '{entity.name}' 的数据库ID，跳过其关系")
                    continue

                # 1. 存储调用关系 (call_relations)
                if entity.calls:
                    for callee_name in entity.calls:
                        callee_id = name_to_entity_id.get(callee_name)
                        if callee_id:
                            call_relations_batch.append((entity_id, callee_id))
                        else:
                            logger.debug(
                                f"未找到被调用实体 '{callee_name}'，跳过调用关系"
                            )

                # 2. 存储继承关系 - extends (relation_type=1)
                if entity.extends:
                    parent_id = name_to_entity_id.get(entity.extends)
                    if parent_id:
                        self.relation_repo.insert_inheritance_relation(
                            child_id=entity_id,
                            parent_id=parent_id,
                            relation_type=1
                        )
                        total_relations += 1
                    else:
                        logger.warning(
                            f"未找到父类实体 '{entity.extends}'，跳过继承关系"
                        )

                # 3. 存储继承关系 - implements (relation_type=2)
                if entity.implements:
                    for interface_name in entity.implements:
                        parent_id = name_to_entity_id.get(interface_name)
                        if parent_id:
                            self.relation_repo.insert_inheritance_relation(
                                child_id=entity_id,
                                parent_id=parent_id,
                                relation_type=2
                            )
                            total_relations += 1
                        else:
                            logger.warning(
                                f"未找到接口实体 '{interface_name}'，跳过实现关系"
                            )

                # 4. 存储组件关系 (component_relations)
                from parsers.arkts_parser import EntityType
                if entity.entity_type == EntityType.COMPONENT and entity.references:
                    for ref_name in entity.references:
                        ref_id = name_to_entity_id.get(ref_name)
                        if ref_id:
                            self.relation_repo.insert_component_relation(
                                parent_id=entity_id,
                                child_id=ref_id,
                                relation_type=1
                            )
                            total_relations += 1
                        else:
                            logger.debug(
                                f"未找到引用的组件实体 '{ref_name}'，跳过组件关系"
                            )

            # 5. 存储导入关系 (import_relations)
            if result.imports:
                for imp in result.imports:
                    source = imp.get("source", "")
                    is_default = imp.get("default") is not None
                    namespace = imp.get("namespace")

                    # 尝试查找导入文件的ID
                    imported_file_id = path_to_file_id.get(source)

                    # 存储默认导入
                    if imp.get("default"):
                        self.relation_repo.insert_import_relation(
                            file_id=file_id,
                            imported_file_id=imported_file_id,
                            imported_name=imp["default"],
                            is_default=True
                        )
                        total_relations += 1

                    # 存储命名空间导入
                    if namespace:
                        self.relation_repo.insert_import_relation(
                            file_id=file_id,
                            imported_file_id=imported_file_id,
                            imported_name=namespace,
                            is_default=False
                        )
                        total_relations += 1

                    # 存储命名导入
                    for named in imp.get("named", []):
                        # 处理 "B as C" 的别名语法
                        alias = None
                        clean_name = named.strip()
                        if " as " in clean_name:
                            parts = clean_name.split(" as ", 1)
                            clean_name = parts[0].strip()
                            alias = parts[1].strip()

                        self.relation_repo.insert_import_relation(
                            file_id=file_id,
                            imported_file_id=imported_file_id,
                            imported_name=clean_name,
                            is_default=False,
                            alias=alias
                        )
                        total_relations += 1

        # 批量插入调用关系
        if call_relations_batch:
            inserted = self.relation_repo.insert_call_relations_batch(
                call_relations_batch,
                batch_size=self.batch_size
            )
            total_relations += inserted
            logger.info(f"批量插入调用关系: {inserted} 条")

        logger.info(f"关系存储完成，共存储 {total_relations} 条关系")
        return total_relations

    def get_statistics(self) -> Dict[str, Any]:
        """获取流水线统计"""
        return {
            "project_path": str(self.project_path),
            "max_workers": self.max_workers,
            "batch_size": self.batch_size
        }
