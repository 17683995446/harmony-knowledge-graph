"""
Entity Repository - 实体仓库
实体的增删改查操作
"""

import hashlib
from typing import List, Dict, Optional

from database.connection_pool import ConnectionPool, get_database_manager
from core.logger_manager import get_logger

logger = get_logger("entity_repository")


class EntityRepository:
    """实体仓库类"""

    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_database_manager().get_pool()
        self._name_cache: Dict[str, int] = {}
        self._name_cache_max = 10000

    def _get_or_create_name(self, name: str, conn=None) -> int:
        """获取或创建名称ID，支持传入外部连接避免数据库锁"""
        if name in self._name_cache:
            return self._name_cache[name]

        own_conn = conn is None
        if own_conn:
            conn = self.pool.get_connection()

        try:
            name_hash = int(hashlib.md5(name.encode('utf-8')).hexdigest()[:8], 16)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO names (name, hash) VALUES (?, ?)",
                (name, name_hash)
            )

            cursor = conn.execute(
                "SELECT id FROM names WHERE name = ?",
                (name,)
            )
            name_id = cursor.fetchone()[0]

            self._name_cache[name] = name_id
            # Prevent unbounded cache growth
            if len(self._name_cache) > self._name_cache_max:
                self._name_cache.clear()
            if own_conn:
                conn.commit()
            return name_id
        finally:
            if own_conn:
                self.pool.release_connection(conn)

    def get_entities_by_file(self, file_id: int) -> List[Dict]:
        """获取文件的所有实体"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, n.name as entity_name, et.name as type_name
                FROM entities e
                JOIN names n ON e.name_id = n.id
                JOIN entity_types et ON e.type_id = et.id
                WHERE e.file_id = ?
                ORDER BY e.line_start
                """,
                (file_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
