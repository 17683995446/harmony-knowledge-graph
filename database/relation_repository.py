"""
Relation Repository - 关系仓库
管理实体间的关系：调用、继承、包含等
"""

from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

from database.connection_pool import ConnectionPool, get_database_manager
from core.logger_manager import get_logger

logger = get_logger("relation_repository")


@dataclass
class CallRelation:
    """调用关系"""
    caller_id: int
    callee_id: int
    call_count: int = 1


@dataclass
class InheritanceRelation:
    """继承关系"""
    child_id: int
    parent_id: int
    relation_type: int  # 1=extends, 2=implements


class RelationRepository:
    """关系仓库类"""
    
    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_database_manager().get_pool()
    
    # ==================== 调用关系 ====================
    
    def insert_call_relation(self, caller_id: int, callee_id: int) -> None:
        """插入调用关系"""
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO call_relations (caller_id, callee_id, call_count)
                VALUES (?, ?, 1)
                ON CONFLICT(caller_id, callee_id) 
                DO UPDATE SET call_count = call_count + 1
                """,
                (caller_id, callee_id)
            )
            conn.commit()
    
    def insert_call_relations_batch(self, relations: List[Tuple[int, int]], batch_size: int = 1000) -> int:
        """批量插入调用关系"""
        count = 0
        
        with self.pool.connection() as conn:
            batch = []
            
            for caller_id, callee_id in relations:
                batch.append((caller_id, callee_id))
                
                if len(batch) >= batch_size:
                    conn.executemany(
                        """
                        INSERT INTO call_relations (caller_id, callee_id, call_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(caller_id, callee_id) 
                        DO UPDATE SET call_count = call_count + 1
                        """,
                        batch
                    )
                    count += len(batch)
                    batch = []
            
            if batch:
                conn.executemany(
                    """
                    INSERT INTO call_relations (caller_id, callee_id, call_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(caller_id, callee_id) 
                    DO UPDATE SET call_count = call_count + 1
                    """,
                    batch
                )
                count += len(batch)
            
            conn.commit()
        
        return count
    
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
            if entity_ids:
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
    
    def insert_inheritance_relation(
        self,
        child_id: int,
        parent_id: int,
        relation_type: int = 1
    ) -> None:
        """插入继承关系"""
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO inheritance_relations 
                (child_id, parent_id, relation_type)
                VALUES (?, ?, ?)
                """,
                (child_id, parent_id, relation_type)
            )
            conn.commit()
    
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
    
    # ==================== 组件关系 ====================
    
    def insert_component_relation(
        self,
        parent_id: int,
        child_id: int,
        relation_type: int = 1
    ) -> None:
        """插入组件关系"""
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO component_relations 
                (parent_id, child_id, relation_type)
                VALUES (?, ?, ?)
                """,
                (parent_id, child_id, relation_type)
            )
            conn.commit()
    
    def get_component_tree(self, root_id: int, max_depth: int = 20) -> Dict:
        """获取组件树（迭代实现，避免递归栈溢出和连接池耗尽）"""
        tree = {"id": root_id, "children": []}
        visited = {root_id}
        queue = [(root_id, tree, 0)]

        with self.pool.connection() as conn:
            while queue:
                current_id, current_node, depth = queue.pop(0)
                if depth >= max_depth:
                    continue
                try:
                    cursor = conn.execute(
                        """
                        SELECT cr.child_id, n.name as child_name
                        FROM component_relations cr
                        JOIN entities e ON cr.child_id = e.id
                        JOIN names n ON e.name_id = n.id
                        WHERE cr.parent_id = ?
                        """,
                        (current_id,)
                    )
                    for row in cursor.fetchall():
                        child_id = row["child_id"]
                        if child_id not in visited:
                            visited.add(child_id)
                            child_node = {"id": child_id, "name": row["child_name"], "children": []}
                            current_node["children"].append(child_node)
                            queue.append((child_id, child_node, depth + 1))
                except Exception:
                    break

        return tree
    
    # ==================== 导入关系 ====================
    
    def insert_import_relation(
        self,
        file_id: int,
        imported_file_id: Optional[int],
        imported_name: str,
        is_default: bool = False,
        alias: Optional[str] = None
    ) -> None:
        """插入导入关系"""
        from database.entity_repository import EntityRepository
        
        entity_repo = EntityRepository(self.pool)
        imported_name_id = entity_repo._get_or_create_name(imported_name)
        alias_id = entity_repo._get_or_create_name(alias) if alias else None
        
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO import_relations 
                (file_id, imported_file_id, imported_name_id, is_default, alias_name_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, imported_file_id, imported_name_id, 1 if is_default else 0, alias_id)
            )
            conn.commit()
    
    def get_file_dependencies(self, file_id: int) -> List[Dict]:
        """获取文件依赖"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT ir.*, f.path as imported_path, n.name as imported_name
                FROM import_relations ir
                LEFT JOIN files f ON ir.imported_file_id = f.id
                JOIN names n ON ir.imported_name_id = n.id
                WHERE ir.file_id = ?
                """,
                (file_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_reverse_dependencies(self, file_id: int) -> List[Dict]:
        """获取反向依赖（哪些文件依赖此文件）"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT ir.*, f.path as importer_path
                FROM import_relations ir
                JOIN files f ON ir.file_id = f.id
                WHERE ir.imported_file_id = ?
                """,
                (file_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== 删除操作 ====================
    
    def delete_relations_by_file(self, file_id: int) -> None:
        """删除文件的所有关系"""
        with self.pool.connection() as conn:
            # 删除调用关系
            conn.execute(
                """
                DELETE FROM call_relations 
                WHERE caller_id IN (SELECT id FROM entities WHERE file_id = ?)
                   OR callee_id IN (SELECT id FROM entities WHERE file_id = ?)
                """,
                (file_id, file_id)
            )
            
            # 删除继承关系
            conn.execute(
                """
                DELETE FROM inheritance_relations 
                WHERE child_id IN (SELECT id FROM entities WHERE file_id = ?)
                   OR parent_id IN (SELECT id FROM entities WHERE file_id = ?)
                """,
                (file_id, file_id)
            )
            
            # 删除组件关系
            conn.execute(
                """
                DELETE FROM component_relations 
                WHERE parent_id IN (SELECT id FROM entities WHERE file_id = ?)
                   OR child_id IN (SELECT id FROM entities WHERE file_id = ?)
                """,
                (file_id, file_id)
            )
            
            # 删除导入关系
            conn.execute(
                "DELETE FROM import_relations WHERE file_id = ?",
                (file_id,)
            )
            
            conn.commit()
    
    # ==================== 统计 ====================
    
    def get_relation_statistics(self) -> Dict:
        """获取关系统计"""
        with self.pool.connection() as conn:
            stats = {}
            
            # 调用关系数
            cursor = conn.execute("SELECT COUNT(*) FROM call_relations")
            stats["call_relations"] = cursor.fetchone()[0]
            
            # 继承关系数
            cursor = conn.execute("SELECT COUNT(*) FROM inheritance_relations")
            stats["inheritance_relations"] = cursor.fetchone()[0]
            
            # 组件关系数
            cursor = conn.execute("SELECT COUNT(*) FROM component_relations")
            stats["component_relations"] = cursor.fetchone()[0]
            
            # 导入关系数
            cursor = conn.execute("SELECT COUNT(*) FROM import_relations")
            stats["import_relations"] = cursor.fetchone()[0]
            
            return stats
    
    def find_circular_dependencies(self) -> List[List[int]]:
        """查找循环依赖"""
        # 构建依赖图
        graph = defaultdict(set)
        
        with self.pool.connection() as conn:
            cursor = conn.execute(
                "SELECT file_id, imported_file_id FROM import_relations WHERE imported_file_id IS NOT NULL"
            )
            
            for row in cursor.fetchall():
                graph[row["file_id"]].add(row["imported_file_id"])
        
        # DFS查找循环
        cycles = []
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in graph[node]:
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # 发现循环
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
            
            path.pop()
            rec_stack.remove(node)
        
        for node in list(graph.keys()):
            if node not in visited:
                dfs(node)
        
        return cycles
