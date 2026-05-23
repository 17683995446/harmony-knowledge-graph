"""
Schema Manager - 数据库模式管理器
定义最优数据结构，全部用数字ID代替文字
"""

import sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from core.logger_manager import get_logger

logger = get_logger("schema_manager")


@dataclass
class TableSchema:
    """表结构定义"""
    name: str
    columns: List[Tuple[str, str]]  # (列名, 类型)
    indexes: List[Tuple[str, List[str]]]  # (索引名, 列列表)
    primary_key: Optional[str] = None
    unique_constraints: List[List[str]] = None
    is_fts5: bool = False  # 是否为FTS5虚拟表
    fts5_columns: Optional[List[str]] = None  # FTS5表的列（不含rowid列）


class DatabaseSchema:
    """数据库模式定义"""

    # FTS5虚拟表名称集合，用于快速判断
    FTS5_TABLE_NAMES = {"search_index"}

    # 核心表定义 - 全部使用数字ID
    TABLES = [
        # 文件表
        TableSchema(
            name="files",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("path", "TEXT NOT NULL"),
                ("hash", "TEXT"),
                ("size", "INTEGER"),
                ("modified_time", "REAL"),
                ("parsed_at", "REAL"),
            ],
            indexes=[
                ("idx_files_path", ["path"]),
                ("idx_files_hash", ["hash"]),
            ],
            unique_constraints=[["path"]]
        ),

        # 实体类型表（枚举值）
        TableSchema(
            name="entity_types",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("name", "TEXT UNIQUE NOT NULL"),
            ],
            indexes=[
                ("idx_entity_types_name", ["name"]),
            ]
        ),

        # 实体表 - 核心表
        TableSchema(
            name="entities",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("name_id", "INTEGER NOT NULL REFERENCES names(id)"),
                ("type_id", "INTEGER NOT NULL REFERENCES entity_types(id)"),
                ("file_id", "INTEGER NOT NULL REFERENCES files(id)"),
                ("parent_id", "INTEGER REFERENCES entities(id)"),
                ("line_start", "INTEGER"),
                ("line_end", "INTEGER"),
                ("column_start", "INTEGER"),
                ("column_end", "INTEGER"),
                ("documentation", "TEXT"),
                ("flags", "INTEGER"),  # 位掩码标记
            ],
            indexes=[
                ("idx_entities_file", ["file_id"]),
                ("idx_entities_type", ["type_id"]),
                ("idx_entities_parent", ["parent_id"]),
                ("idx_entities_name", ["name_id"]),
            ]
        ),

        # 名称表 - 去重存储所有名称
        TableSchema(
            name="names",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("name", "TEXT UNIQUE NOT NULL"),
                ("hash", "INTEGER"),  # 名称哈希，加速查找
            ],
            indexes=[
                ("idx_names_hash", ["hash"]),
            ]
        ),

        # 类型名称表 - 存储类型字符串
        TableSchema(
            name="type_names",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("name", "TEXT UNIQUE NOT NULL"),
            ],
            indexes=[]
        ),

        # 实体类型关联表
        TableSchema(
            name="entity_type_refs",
            columns=[
                ("entity_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("type_name_id", "INTEGER NOT NULL REFERENCES type_names(id)"),
            ],
            indexes=[
                ("idx_entity_type_refs_entity", ["entity_id"]),
                ("idx_entity_type_refs_type", ["type_name_id"]),
            ],
            unique_constraints=[["entity_id", "type_name_id"]]
        ),

        # 方法参数表
        TableSchema(
            name="method_params",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("method_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("name_id", "INTEGER NOT NULL REFERENCES names(id)"),
                ("type_name_id", "INTEGER REFERENCES type_names(id)"),
                ("position", "INTEGER"),
                ("default_value", "TEXT"),
            ],
            indexes=[
                ("idx_method_params_method", ["method_id"]),
            ]
        ),

        # 调用关系表 - 只存两个数字ID
        TableSchema(
            name="call_relations",
            columns=[
                ("caller_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("callee_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("call_count", "INTEGER DEFAULT 1"),
            ],
            indexes=[
                ("idx_calls_caller", ["caller_id"]),
                ("idx_calls_callee", ["callee_id"]),
            ],
            unique_constraints=[["caller_id", "callee_id"]]
        ),

        # 继承关系表
        TableSchema(
            name="inheritance_relations",
            columns=[
                ("child_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("parent_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("relation_type", "INTEGER"),  # 1=extends, 2=implements
            ],
            indexes=[
                ("idx_inheritance_child", ["child_id"]),
                ("idx_inheritance_parent", ["parent_id"]),
            ],
            unique_constraints=[["child_id", "parent_id"]]
        ),

        # 组件包含关系表（UI组件父子关系）
        TableSchema(
            name="component_relations",
            columns=[
                ("parent_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("child_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("relation_type", "INTEGER"),  # 1=contains, 2=renders
            ],
            indexes=[
                ("idx_component_parent", ["parent_id"]),
                ("idx_component_child", ["child_id"]),
            ],
            unique_constraints=[["parent_id", "child_id"]]
        ),

        # 导入关系表
        TableSchema(
            name="import_relations",
            columns=[
                ("file_id", "INTEGER NOT NULL REFERENCES files(id)"),
                ("imported_file_id", "INTEGER REFERENCES files(id)"),
                ("imported_name_id", "INTEGER REFERENCES names(id)"),
                ("is_default", "INTEGER"),  # 0/1
                ("alias_name_id", "INTEGER REFERENCES names(id)"),
            ],
            indexes=[
                ("idx_imports_file", ["file_id"]),
                ("idx_imports_imported", ["imported_file_id"]),
            ]
        ),

        # 装饰器表
        TableSchema(
            name="decorators",
            columns=[
                ("id", "INTEGER PRIMARY KEY"),
                ("entity_id", "INTEGER NOT NULL REFERENCES entities(id)"),
                ("name_id", "INTEGER NOT NULL REFERENCES names(id)"),
                ("arguments", "TEXT"),  # JSON格式
            ],
            indexes=[
                ("idx_decorators_entity", ["entity_id"]),
            ]
        ),

        # 代码度量表
        TableSchema(
            name="code_metrics",
            columns=[
                ("file_id", "INTEGER PRIMARY KEY REFERENCES files(id)"),
                ("total_lines", "INTEGER"),
                ("code_lines", "INTEGER"),
                ("comment_lines", "INTEGER"),
                ("blank_lines", "INTEGER"),
                ("complexity", "INTEGER"),
                ("entity_count", "INTEGER"),
            ],
            indexes=[]
        ),

        # 全文搜索索引表（FTS5虚拟表）
        # FTS5虚拟表不能使用常规CREATE TABLE语法，也不能创建常规索引
        # 使用CREATE VIRTUAL TABLE ... USING fts5(...)创建
        TableSchema(
            name="search_index",
            columns=[
                ("entity_id", "INTEGER"),
                ("name", "TEXT"),
                ("content", "TEXT"),
            ],
            indexes=[],
            is_fts5=True,
            fts5_columns=["name", "content"],  # FTS5索引列，entity_id作为隐藏rowid的UNINDEXED列
        ),
    ]

    # 实体类型枚举值
    ENTITY_TYPES = [
        (1, "class"),
        (2, "interface"),
        (3, "enum"),
        (4, "method"),
        (5, "function"),
        (6, "property"),
        (7, "variable"),
        (8, "import"),
        (9, "export"),
        (10, "decorator"),
        (11, "component"),
    ]


class SchemaManager:
    """数据库模式管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.schema = DatabaseSchema()

    def initialize_database(self) -> None:
        """初始化数据库，创建所有表"""
        logger.info(f"初始化数据库: {self.db_path}")

        # 确保目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # 检查数据库文件是否损坏
        if Path(self.db_path).exists():
            is_corrupted = False
            try:
                with sqlite3.connect(self.db_path, timeout=5) as test_conn:
                    # 完整性检查
                    result = test_conn.execute("PRAGMA integrity_check").fetchone()
                    if result and result[0] != "ok":
                        is_corrupted = True
            except sqlite3.DatabaseError:
                # 真正的数据库损坏（文件格式错误等）
                is_corrupted = True
            except (sqlite3.OperationalError, OSError):
                # 数据库被锁定或文件系统错误 - 不视为损坏，跳过重建
                logger.debug("数据库暂时不可访问（可能被锁定），跳过完整性检查")
                return
            
            if is_corrupted:
                logger.warning("数据库文件损坏，删除并重新创建")
                try:
                    Path(self.db_path).unlink()
                except Exception as e:
                    logger.error(f"无法删除损坏的数据库文件: {e}")
                    raise

        with sqlite3.connect(self.db_path) as conn:
            # 启用外键
            conn.execute("PRAGMA foreign_keys = ON")

            # 性能优化设置
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -64000")  # 64MB缓存
            conn.execute("PRAGMA temp_store = MEMORY")

            cursor = conn.cursor()

            # 创建表
            for table in self.schema.TABLES:
                self._create_table(cursor, table)

            # 插入实体类型枚举值
            self._insert_entity_types(cursor)

            conn.commit()

        logger.info("数据库初始化完成")

    def _create_table(self, cursor: sqlite3.Cursor, table: TableSchema) -> None:
        """创建单个表

        对于FTS5虚拟表，使用CREATE VIRTUAL TABLE语法，
        并跳过常规索引的创建（FTS5自带全文搜索索引）。
        """
        if table.is_fts5:
            # FTS5虚拟表：使用特殊的CREATE VIRTUAL TABLE语法
            # FTS5表不能使用常规的CREATE TABLE IF NOT EXISTS
            fts5_cols = ", ".join(table.fts5_columns)
            create_sql = (
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table.name} "
                f"USING fts5({fts5_cols})"
            )
            cursor.execute(create_sql)
            logger.debug(f"创建FTS5虚拟表: {table.name}")
            return

        # 常规表：构建列定义
        columns_def = []
        for col_name, col_type in table.columns:
            columns_def.append(f"{col_name} {col_type}")

        # 添加主键约束（如果不是在列定义中）
        if table.primary_key and not any("PRIMARY KEY" in c[1] for c in table.columns):
            columns_def.append(f"PRIMARY KEY ({table.primary_key})")

        # 添加唯一约束
        if table.unique_constraints:
            for constraint in table.unique_constraints:
                columns_def.append(f"UNIQUE ({', '.join(constraint)})")

        # 创建表
        create_sql = f"CREATE TABLE IF NOT EXISTS {table.name} ({', '.join(columns_def)})"
        cursor.execute(create_sql)

        # 创建索引（FTS5虚拟表不能创建常规索引，已在上面的return中跳过）
        for index_name, columns in table.indexes:
            index_sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table.name} ({', '.join(columns)})"
            cursor.execute(index_sql)

        logger.debug(f"创建表: {table.name}")

    def _insert_entity_types(self, cursor: sqlite3.Cursor) -> None:
        """插入实体类型枚举值"""
        cursor.executemany(
            "INSERT OR IGNORE INTO entity_types (id, name) VALUES (?, ?)",
            self.schema.ENTITY_TYPES
        )

    def reset_database(self) -> None:
        """重置数据库（删除所有数据）

        注意：DROP TABLE IF EXISTS对FTS5虚拟表同样有效，
        SQLite会正确清理虚拟表及其关联的内部结构。
        """
        logger.warning("重置数据库...")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 禁用外键约束，避免DROP TABLE时因外键引用失败
            conn.execute("PRAGMA foreign_keys = OFF")

            # 删除所有表（包括FTS5虚拟表）
            # 反向遍历以正确处理外键依赖关系
            for table in reversed(self.schema.TABLES):
                cursor.execute(f"DROP TABLE IF EXISTS {table.name}")

            conn.commit()

        # 重新初始化
        self.initialize_database()
        logger.info("数据库重置完成")

    def get_table_stats(self) -> Dict[str, int]:
        """获取各表统计信息"""
        stats = {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            for table in self.schema.TABLES:
                cursor.execute(f"SELECT COUNT(*) FROM {table.name}")
                count = cursor.fetchone()[0]
                stats[table.name] = count

        return stats

    def optimize_database(self) -> None:
        """优化数据库"""
        logger.info("优化数据库...")

        with sqlite3.connect(self.db_path) as conn:
            # 分析表
            conn.execute("ANALYZE")

            # 清理空闲页
            conn.execute("VACUUM")

            # 重新索引
            conn.execute("REINDEX")

        logger.info("数据库优化完成")
