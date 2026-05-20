"""
Database Module - 数据库模块
SQLite数据库管理，最优数据结构设计

注意：使用延迟初始化，避免导入时产生副作用。
实际使用时通过 get_database_manager() 获取实例。
"""

from .schema_manager import SchemaManager, DatabaseSchema
from .connection_pool import ConnectionPool, get_database_manager
from .entity_repository import EntityRepository
from .relation_repository import RelationRepository
from .query_executor import QueryExecutor

__all__ = [
    "SchemaManager",
    "DatabaseSchema",
    "ConnectionPool",
    "get_database_manager",
    "EntityRepository",
    "RelationRepository",
    "QueryExecutor"
]
