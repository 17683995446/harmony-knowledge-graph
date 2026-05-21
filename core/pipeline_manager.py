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
from core.parallel_processor import ParallelProcessor
from parsers.file_scanner import FileScanner, FileInfo
from parsers.arkts_parser import ArkTSParser, ParseResult
from parsers.ast_analyzer import ASTAnalyzer
from database.connection_pool import get_database_manager
from database.entity_repository import EntityRepository
from database.relation_repository import RelationRepository
from utils.trace_logger import trace_call, trace_line, TraceContext

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
        trace_line(f"PipelineManager.__init__ START: project_path={project_path}", "info")
        self.project_path = Path(project_path).resolve()
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.config = get_configuration()
        trace_line(f"PipelineManager.__init__ END: config loaded", "info")

        # 初始化组件
        trace_line("Initializing components...", "debug")
        self.file_scanner = FileScanner(str(self.project_path))
        trace_line("FileScanner initialized", "debug")
        
        self.parallel_processor = ParallelProcessor(
            max_workers=self.max_workers,
            show_progress=True
        )
        trace_line("ParallelProcessor initialized", "debug")
        
        self.ast_analyzer = ASTAnalyzer()
        trace_line("ASTAnalyzer initialized", "debug")
        
        self.entity_repo = EntityRepository()
        trace_line("EntityRepository initialized", "debug")
        
        self.relation_repo = RelationRepository()
        trace_line("RelationRepository initialized", "debug")
        
        trace_line("PipelineManager.__init__ COMPLETE", "info")

    @trace_call
    def run_full_pipeline(self, incremental: bool = False) -> PipelineResult:
        """运行完整流水线"""
        trace_line(f"run_full_pipeline START: incremental={incremental}", "info")
        start_time = time.time()
        stages = {}

        try:
            # 阶段1: 扫描文件
            trace_line("STAGE 1: File scanning", "info")
            with TraceContext("file_scanning"):
                file_infos = self._scan_files()
            stages['scan'] = {'files': len(file_infos)}
            trace_line(f"STAGE 1 COMPLETE: {len(file_infos)} files found", "info")

            if not file_infos:
                trace_line("No files found, returning early", "warning")
                return PipelineResult(
                    success=True,
                    scanned_files=0,
                    duration=time.time() - start_time,
                    stages=stages
                )

            # 阶段2: 解析文件
            trace_line("STAGE 2: File parsing", "info")
            with TraceContext("file_parsing"):
                parse_results = self._parse_files(file_infos)
            total_entities = sum(len(r.entities) for r in parse_results)
            stages['parse'] = {'files': len(parse_results), 'entities': total_entities}
            trace_line(f"STAGE 2 COMPLETE: {len(parse_results)} files parsed, {total_entities} entities", "info")

            # 阶段3: 存储文件
            trace_line("STAGE 3: File storage", "info")
            with TraceContext("file_storage"):
                self._store_files(file_infos, incremental)
            stages['store_files'] = {'files': len(file_infos)}
            trace_line(f"STAGE 3 COMPLETE: {len(file_infos)} files stored", "info")

            # 阶段4: 存储实体（带事务）
            trace_line("STAGE 4: Entity storage", "info")
            with TraceContext("entity_storage"):
                stored_entities = self._store_entities(parse_results)
            stages['store_entities'] = {'entities': stored_entities}
            trace_line(f"STAGE 4 COMPLETE: {stored_entities} entities stored", "info")

            # 阶段5: 存储关系
            trace_line("STAGE 5: Relation storage", "info")
            with TraceContext("relation_storage"):
                stored_relations = self._store_relations(parse_results)
            stages['store_relations'] = {'relations': stored_relations}
            trace_line(f"STAGE 5 COMPLETE: {stored_relations} relations stored", "info")

            # 阶段6: AST分析
            trace_line("STAGE 6: AST analysis", "info")
            with TraceContext("ast_analysis"):
                analysis = self.ast_analyzer.analyze_results(parse_results)
            stages['analysis'] = analysis
            trace_line(f"STAGE 6 COMPLETE: analysis done", "info")

            duration = time.time() - start_time
            trace_line(f"run_full_pipeline COMPLETE: success=True, duration={duration:.2f}s", "info")

            return PipelineResult(
                success=True,
                scanned_files=len(file_infos),
                parsed_entities=stored_entities,
                found_relations=stored_relations,
                duration=duration,
                stages=stages
            )

        except Exception as e:
            duration = time.time() - start_time
            trace_line(f"run_full_pipeline FAILED: {type(e).__name__}: {str(e)}", "error")
            logger.error(f"Pipeline failed: {e}")
            return PipelineResult(
                success=False,
                error=str(e),
                duration=duration,
                stages=stages
            )

    @trace_call
    def _scan_files(self) -> List[FileInfo]:
        """扫描文件"""
        trace_line("_scan_files START", "debug")
        files = self.file_scanner.scan()
        trace_line(f"_scan_files END: {len(files)} files", "debug")
        return files

    @trace_call
    def _parse_files(self, file_infos: List[FileInfo]) -> List[ParseResult]:
        """解析文件"""
        trace_line(f"_parse_files START: {len(file_infos)} files to parse", "debug")
        
        def parse_single(file_info: FileInfo) -> ParseResult:
            trace_line(f"Parsing file: {file_info.path}", "debug")
            local_parser = ArkTSParser()  # Each thread gets its own parser
            result = local_parser.parse_file(file_info.path)
            trace_line(f"Parsed file: {file_info.path}, {len(result.entities)} entities", "debug")
            return result

        results = self.parallel_processor.process_items(
            file_infos,
            parse_single,
            error_handler=lambda item, e: trace_line(f"Failed to parse {item.path}: {e}", "error")
        )

        successful = [r.data for r in results if r.success and r.data]
        trace_line(f"_parse_files END: {len(successful)}/{len(file_infos)} files parsed successfully", "debug")
        return successful

    @trace_call
    def _store_files(self, file_infos: List[FileInfo], incremental: bool) -> None:
        """存储文件信息"""
        trace_line(f"_store_files START: {len(file_infos)} files, incremental={incremental}", "debug")

        db_manager = get_database_manager()
        trace_line(f"Got database manager", "debug")

        with db_manager.get_pool().connection() as conn:
            try:
                conn.execute("BEGIN")

                stored = 0
                skipped = 0

                for file_info in file_infos:
                    relative_path = self._resolve_relative_path(file_info.path)
                    trace_line(f"Processing file: {relative_path}", "debug")

                    # 检查是否已存在
                    existing = conn.execute(
                        "SELECT id, hash FROM files WHERE path = ?",
                        (relative_path,)
                    ).fetchone()

                    if existing:
                        if incremental and existing["hash"] == file_info.content_hash:
                            trace_line(f"File unchanged, skipping: {relative_path}", "debug")
                            skipped += 1
                            continue
                        else:
                            trace_line(f"File changed, updating: {relative_path}", "debug")
                            conn.execute(
                                "UPDATE files SET hash = ?, size = ?, modified_time = ? WHERE id = ?",
                                (file_info.content_hash, file_info.size, file_info.modified_time, existing["id"])
                            )
                            stored += 1
                    else:
                        trace_line(f"New file, inserting: {relative_path}", "debug")
                        conn.execute(
                            "INSERT INTO files (path, hash, size, modified_time) VALUES (?, ?, ?, ?)",
                            (relative_path, file_info.content_hash, file_info.size, file_info.modified_time)
                        )
                        stored += 1

                conn.commit()
                trace_line(f"_store_files END: {stored} stored, {skipped} skipped", "debug")

            except Exception:
                conn.rollback()
                raise

    @trace_call
    def _store_entities(self, parse_results: List[ParseResult]) -> int:
        """存储实体（带事务保证原子性）"""
        trace_line(f"_store_entities START: {len(parse_results)} parse results", "debug")
        
        from database.connection_pool import get_database_manager
        db_manager = get_database_manager()
        trace_line(f"Got database manager", "debug")
        
        total_entities = 0

        for result in parse_results:
            relative_path = self._resolve_relative_path(result.file_path)
            trace_line(f"Processing entities for: {relative_path}", "debug")
            
            file_row = db_manager.fetch_one(
                "SELECT id FROM files WHERE path = ?",
                (relative_path,)
            )

            if not file_row:
                trace_line(f"File not found in DB, skipping: {relative_path}", "warning")
                continue

            file_id = file_row["id"]
            trace_line(f"File ID: {file_id}", "debug")

            # 准备实体数据
            entities_to_insert = []
            for entity in result.entities:
                entities_to_insert.append((entity, file_id))
            
            trace_line(f"Prepared {len(entities_to_insert)} entities for insertion", "debug")

            # 使用显式事务
            with db_manager.get_pool().connection() as conn:
                try:
                    trace_line("BEGIN transaction", "debug")
                    conn.execute("BEGIN")
                    
                    # 删除旧实体
                    trace_line(f"Deleting old entities for file_id={file_id}", "debug")
                    conn.execute(
                        "DELETE FROM method_params WHERE method_id IN (SELECT id FROM entities WHERE file_id = ?)",
                        (file_id,)
                    )
                    conn.execute(
                        "DELETE FROM decorators WHERE entity_id IN (SELECT id FROM entities WHERE file_id = ?)",
                        (file_id,)
                    )
                    deleted = conn.execute("DELETE FROM entities WHERE file_id = ?", (file_id,)).rowcount
                    trace_line(f"Deleted {deleted} old entities", "debug")
                    
                    # 确保名称存在
                    trace_line("Ensuring names exist", "debug")
                    all_names = set()
                    for entity, _ in entities_to_insert:
                        all_names.add(entity.name)
                        if entity.extends:
                            all_names.add(entity.extends)
                        if entity.implements:
                            all_names.update(entity.implements)
                        for call in entity.calls:
                            all_names.add(call)
                    
                    trace_line(f"Total unique names: {len(all_names)}", "debug")
                    
                    for name in all_names:
                        if name:
                            conn.execute(
                                "INSERT OR IGNORE INTO names (name, hash) VALUES (?, ?)",
                                (name, 0)
                            )
                    
                    # 插入实体
                    trace_line(f"Inserting {len(entities_to_insert)} entities", "debug")
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
                        else:
                            trace_line(f"Missing name or type for entity: {entity.name}", "warning")
                    
                    trace_line("COMMIT transaction", "debug")
                    conn.commit()
                    trace_line(f"Transaction committed, total_entities={total_entities}", "debug")
                    
                except Exception as e:
                    trace_line(f"ROLLBACK transaction: {e}", "error")
                    conn.rollback()
                    logger.error(f"存储实体失败，已回滚: {e}")
                    raise

        trace_line(f"_store_entities END: {total_entities} entities stored", "debug")
        return total_entities

    @trace_call
    def _store_relations(self, parse_results: List[ParseResult]) -> int:
        """存储关系"""
        trace_line(f"_store_relations START: {len(parse_results)} parse results", "debug")

        from database.connection_pool import get_database_manager
        db_manager = get_database_manager()
        trace_line(f"Got database manager", "debug")

        total_relations = 0

        # 构建名称 -> 实体ID 的查找字典
        trace_line("Building name_to_entity_id mapping", "debug")
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
        trace_line(f"name_to_entity_id: {len(name_to_entity_id)} entries", "debug")

        # 构建文件路径 -> 文件ID 的查找字典
        trace_line("Building path_to_file_id mapping", "debug")
        path_to_file_id: Dict[str, int] = {}
        file_rows = db_manager.fetch_all("SELECT id, path FROM files")
        for row in file_rows:
            path_to_file_id[row["path"]] = row["id"]
        trace_line(f"path_to_file_id: {len(path_to_file_id)} entries", "debug")

        # 收集所有调用关系，用于批量插入
        call_relations_batch: List[tuple] = []
        # 收集继承关系和导入关系，在同一个事务中处理
        inheritance_batch: List[tuple] = []
        import_batch: List[tuple] = []

        for result in parse_results:
            relative_path = self._resolve_relative_path(result.file_path)
            file_id = path_to_file_id.get(relative_path)
            if not file_id:
                trace_line(f"File not found in mapping: {relative_path}", "warning")
                continue

            trace_line(f"Processing relations for: {relative_path}", "debug")

            for entity in result.entities:
                entity_id = name_to_entity_id.get(entity.name)
                if not entity_id:
                    trace_line(f"Entity not found in mapping: {entity.name}", "debug")
                    continue

                # 1. 收集调用关系
                if entity.calls:
                    trace_line(f"Entity {entity.name} has {len(entity.calls)} calls", "debug")
                    for callee_name in entity.calls:
                        callee_id = name_to_entity_id.get(callee_name)
                        if callee_id:
                            call_relations_batch.append((entity_id, callee_id))
                            trace_line(f"Added call relation: {entity.name} -> {callee_name}", "debug")
                        else:
                            trace_line(f"Callee not found: {callee_name}", "debug")

                # 2. 收集继承关系 - extends
                if entity.extends:
                    trace_line(f"Entity {entity.name} extends {entity.extends}", "debug")
                    parent_id = name_to_entity_id.get(entity.extends)
                    if parent_id:
                        inheritance_batch.append((entity_id, parent_id, 1))
                        total_relations += 1
                        trace_line(f"Added extends relation: {entity.name} -> {entity.extends}", "debug")
                    else:
                        trace_line(f"Parent not found: {entity.extends}", "warning")

                # 3. 收集继承关系 - implements
                if entity.implements:
                    trace_line(f"Entity {entity.name} implements {entity.implements}", "debug")
                    for interface_name in entity.implements:
                        parent_id = name_to_entity_id.get(interface_name)
                        if parent_id:
                            inheritance_batch.append((entity_id, parent_id, 2))
                            total_relations += 1
                            trace_line(f"Added implements relation: {entity.name} -> {interface_name}", "debug")
                        else:
                            trace_line(f"Interface not found: {interface_name}", "warning")

            # 5. 收集导入关系
            if result.imports:
                trace_line(f"File {relative_path} has {len(result.imports)} imports", "debug")
                for imp in result.imports:
                    source = imp.get("source", "")
                    is_default = imp.get("default") is not None
                    namespace = imp.get("namespace")

                    imported_file_id = path_to_file_id.get(source)

                    if imp.get("default"):
                        import_batch.append((file_id, imported_file_id, imp["default"], 1))
                        total_relations += 1

                    if namespace:
                        import_batch.append((file_id, imported_file_id, namespace, 0))
                        total_relations += 1

                    for name in imp.get("named", []):
                        import_batch.append((file_id, imported_file_id, name, 0))
                        total_relations += 1

        # 在单个事务中写入所有关系
        with db_manager.get_pool().connection() as conn:
            try:
                conn.execute("BEGIN")

                # 批量插入调用关系
                if call_relations_batch:
                    trace_line(f"Batch inserting {len(call_relations_batch)} call relations", "debug")
                    conn.executemany(
                        """
                        INSERT INTO call_relations (caller_id, callee_id, call_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(caller_id, callee_id)
                        DO UPDATE SET call_count = call_count + 1
                        """,
                        call_relations_batch
                    )
                    total_relations += len(call_relations_batch)

                # 批量插入继承关系
                if inheritance_batch:
                    trace_line(f"Batch inserting {len(inheritance_batch)} inheritance relations", "debug")
                    conn.executemany(
                        """
                        INSERT OR IGNORE INTO inheritance_relations
                        (child_id, parent_id, relation_type)
                        VALUES (?, ?, ?)
                        """,
                        inheritance_batch
                    )

                # 批量插入导入关系
                if import_batch:
                    trace_line(f"Batch inserting {len(import_batch)} import relations", "debug")
                    for file_id, imported_file_id, imported_name, is_default in import_batch:
                        imported_name_id = self.entity_repo._get_or_create_name(imported_name, conn=conn)
                        conn.execute(
                            """
                            INSERT INTO import_relations
                            (file_id, imported_file_id, imported_name_id, is_default, alias_name_id)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (file_id, imported_file_id, imported_name_id, is_default, None)
                        )

                conn.commit()
                trace_line(f"All relations committed in single transaction", "debug")

            except Exception:
                conn.rollback()
                raise

        trace_line(f"_store_relations END: {total_relations} relations stored", "debug")
        return total_relations

    def _resolve_relative_path(self, file_path: str) -> str:
        """将绝对路径解析为相对于项目根目录的路径"""
        trace_line(f"_resolve_relative_path: {file_path}", "debug")
        
        # 标准化路径分隔符
        normalized_path = os.path.normpath(file_path)
        normalized_project = os.path.normpath(str(self.project_path))
        
        # 获取相对路径
        if normalized_path.startswith(normalized_project):
            relative = normalized_path[len(normalized_project):].lstrip(os.sep)
            # 统一使用正斜杠
            result = relative.replace(os.sep, '/')
            trace_line(f"Resolved to: {result}", "debug")
            return result
        
        trace_line(f"Path not under project, returning as-is: {file_path}", "warning")
        return file_path.replace(os.sep, '/')
