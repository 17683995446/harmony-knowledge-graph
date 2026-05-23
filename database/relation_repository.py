"""
Relation Repository - 关系仓库
管理实体间的关系：调用、继承等
"""

from typing import List, Dict, Optional

from database.connection_pool import ConnectionPool, get_database_manager
from core.logger_manager import get_logger

logger = get_logger("relation_repository")


class RelationRepository:
    """关系仓库类"""

    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_database_manager().get_pool()

    # ==================== 调用关系 ====================

    def get_callees(self, caller_id: int) -> List[Dict]:
        """获取被调用者列表"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT cr.*, n.name as callee_name
                FROM call_relations cr
                JOIN entities e ON cr.callee_id = e.id
                JOIN names n ON e.name_id = n.id
                WHERE cr.caller_id = ?
                """,
                (caller_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_callers(self, callee_id: int) -> List[Dict]:
        """获取调用者列表"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT cr.*, n.name as caller_name
                FROM call_relations cr
                JOIN entities e ON cr.caller_id = e.id
                JOIN names n ON e.name_id = n.id
                WHERE cr.callee_id = ?
                """,
                (callee_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_call_graph(self, entity_ids: Optional[List[int]] = None) -> List[Dict]:
        """获取调用图"""
        with self.pool.connection() as conn:
            if entity_ids is not None:
                placeholders = ','.join('?' * len(entity_ids))
                cursor = conn.execute(
                    f"""
                    SELECT cr.*,
                           nc.name as caller_name,
                           nce.name as callee_name
                    FROM call_relations cr
                    JOIN entities ec ON cr.caller_id = ec.id
                    JOIN entities ee ON cr.callee_id = ee.id
                    JOIN names nc ON ec.name_id = nc.id
                    JOIN names nce ON ee.name_id = nce.id
                    WHERE cr.caller_id IN ({placeholders})
                       OR cr.callee_id IN ({placeholders})
                    """,
                    entity_ids + entity_ids
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT cr.*,
                           nc.name as caller_name,
                           nce.name as callee_name
                    FROM call_relations cr
                    JOIN entities ec ON cr.caller_id = ec.id
                    JOIN entities ee ON cr.callee_id = ee.id
                    JOIN names nc ON ec.name_id = nc.id
                    JOIN names nce ON ee.name_id = nce.id
                    LIMIT 10000
                    """
                )
            return [dict(row) for row in cursor.fetchall()]

    # ==================== 继承关系 ====================

    def get_inheritance_chain(self, entity_id: int) -> List[Dict]:
        """获取继承链"""
        chain = []
        current_id = entity_id
        visited = set()

        with self.pool.connection() as conn:
            while current_id and current_id not in visited:
                visited.add(current_id)

                cursor = conn.execute(
                    """
                    SELECT ir.*, n.name as parent_name
                    FROM inheritance_relations ir
                    JOIN entities e ON ir.parent_id = e.id
                    JOIN names n ON e.name_id = n.id
                    WHERE ir.child_id = ?
                    """,
                    (current_id,)
                )

                row = cursor.fetchone()
                if row:
                    chain.append(dict(row))
                    current_id = row["parent_id"]
                else:
                    break

        return chain

    def get_subclasses(self, parent_id: int) -> List[Dict]:
        """获取所有子类"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT ir.*, n.name as child_name
                FROM inheritance_relations ir
                JOIN entities e ON ir.child_id = e.id
                JOIN names n ON e.name_id = n.id
                WHERE ir.parent_id = ?
                """,
                (parent_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
