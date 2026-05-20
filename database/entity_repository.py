"""
Entity Repository - 实体仓库
实体的增删改查操作，支持批量处理
"""

import hashlib
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

from database.connection_pool import ConnectionPool, get_database_manager
from core.logger_manager import get_logger
from parsers.arkts_parser import ParsedEntity, EntityType

logger = get_logger("entity_repository")


@dataclass
class EntityRecord:
    """实体记录"""
    id: Optional[int]
    name_id: int
    type_id: int
    file_id: int
    parent_id: Optional[int]
    line_start: int
    line_end: int
    column_start: int
    column_end: int
    documentation: Optional[str]
    flags: int


class EntityRepository:
    """实体仓库类"""
    
    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_database_manager().get_pool()
        self._name_cache: Dict[str, int] = {}
        self._type_name_cache: Dict[str, int] = {}
        self._entity_type_cache: Dict[str, int] = {}
    
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
            if own_conn:
                conn.commit()
            return name_id
        finally:
            if own_conn:
                self.pool.release_connection(conn)
    
    def _get_or_create_type_name(self, type_name: str, conn=None) -> int:
        """获取或创建类型名称ID，支持传入外部连接避免数据库锁"""
        if not type_name:
            return 0
        
        if type_name in self._type_name_cache:
            return self._type_name_cache[type_name]
        
        own_conn = conn is None
        if own_conn:
            conn = self.pool.get_connection()
        
        try:
            conn.execute(
                "INSERT OR IGNORE INTO type_names (name) VALUES (?)",
                (type_name,)
            )
            
            cursor = conn.execute(
                "SELECT id FROM type_names WHERE name = ?",
                (type_name,)
            )
            type_id = cursor.fetchone()[0]
            
            self._type_name_cache[type_name] = type_id
            if own_conn:
                conn.commit()
            return type_id
        finally:
            if own_conn:
                self.pool.release_connection(conn)
    
    def _get_entity_type_id(self, entity_type: EntityType, conn=None) -> int:
        """获取实体类型ID，支持传入外部连接避免数据库锁"""
        type_name = entity_type.value
        
        if type_name in self._entity_type_cache:
            return self._entity_type_cache[type_name]
        
        own_conn = conn is None
        if own_conn:
            conn = self.pool.get_connection()
        
        try:
            cursor = conn.execute(
                "SELECT id FROM entity_types WHERE name = ?",
                (type_name,)
            )
            result = cursor.fetchone()
            if result:
                type_id = result[0]
                self._entity_type_cache[type_name] = type_id
                return type_id
        finally:
            if own_conn:
                self.pool.release_connection(conn)
        
        return 0
    
    def insert_entity(self, entity: ParsedEntity, file_id: int) -> int:
        """插入单个实体"""
        name_id = self._get_or_create_name(entity.name)
        type_id = self._get_entity_type_id(entity.entity_type)
        
        # 计算flags
        flags = 0
        if "export" in entity.modifiers:
            flags |= 1
        if "default" in entity.modifiers:
            flags |= 2
        if "abstract" in entity.modifiers:
            flags |= 4
        if "static" in entity.modifiers:
            flags |= 8
        
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO entities 
                (name_id, type_id, file_id, parent_id, line_start, line_end, 
                 column_start, column_end, documentation, flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name_id,
                    type_id,
                    file_id,
                    None,  # parent_id 需要后续处理
                    entity.location.line,
                    entity.location.end_line or entity.location.line,
                    entity.location.column,
                    entity.location.end_column or entity.location.column,
                    entity.documentation,
                    flags
                )
            )
            
            entity_id = cursor.lastrowid
            
            # 插入方法参数
            if entity.parameters:
                self._insert_method_params(conn, entity_id, entity.parameters)
            
            # 插入装饰器
            if entity.annotations:
                self._insert_decorators(conn, entity_id, entity.annotations)
            
            conn.commit()
            return entity_id
    
    def insert_entities_batch(
        self,
        entities: List[Tuple[ParsedEntity, int]],
        batch_size: int = 1000
    ) -> List[int]:
        """批量插入实体"""
        entity_ids = []
        
        # 预缓存所有名称和类型名（在打开连接前完成，避免锁问题）
        all_names = set()
        all_type_names = set()
        for entity, _ in entities:
            all_names.add(entity.name)
            for param in entity.parameters:
                all_names.add(param.get("name", ""))
                if param.get("type"):
                    all_type_names.add(param.get("type"))
            if entity.return_type:
                all_type_names.add(entity.return_type)
        
        for name in all_names:
            if name:
                self._get_or_create_name(name)
        
        for type_name in all_type_names:
            if type_name:
                self._get_or_create_type_name(type_name)
        
        # 批量插入（逐条执行以获取lastrowid，executemany不设置lastrowid）
        with self.pool.connection() as conn:
            for entity, file_id in entities:
                name_id = self._name_cache.get(entity.name, 0)
                type_id = self._get_entity_type_id(entity.entity_type, conn)
                
                flags = 0
                if "export" in entity.modifiers:
                    flags |= 1
                if "default" in entity.modifiers:
                    flags |= 2
                if "abstract" in entity.modifiers:
                    flags |= 4
                if "static" in entity.modifiers:
                    flags |= 8

                cursor = conn.execute(
                    """
                    INSERT INTO entities 
                    (name_id, type_id, file_id, parent_id, line_start, line_end, 
                     column_start, column_end, documentation, flags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name_id,
                        type_id,
                        file_id,
                        None,  # parent_id 需要后续处理
                        entity.location.line,
                        entity.location.end_line or entity.location.line,
                        entity.location.column,
                        entity.location.end_column or entity.location.column,
                        entity.documentation,
                        flags
                    )
                )
                entity_ids.append(cursor.lastrowid)
                
                # 插入方法参数
                if entity.parameters:
                    self._insert_method_params(conn, cursor.lastrowid, entity.parameters)
                
                # 插入装饰器
                if entity.annotations:
                    self._insert_decorators(conn, cursor.lastrowid, entity.annotations)
            
            conn.commit()
        
        return entity_ids
    
    def _insert_method_params(
        self,
        conn,
        method_id: int,
        parameters: List[Dict]
    ) -> None:
        """插入方法参数"""
        for i, param in enumerate(parameters):
            name_id = self._get_or_create_name(param.get("name", ""), conn)
            type_id = self._get_or_create_type_name(param.get("type"), conn)
            
            conn.execute(
                """
                INSERT INTO method_params 
                (method_id, name_id, type_name_id, position, default_value)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    method_id,
                    name_id,
                    type_id if type_id else None,
                    i,
                    param.get("default_value")
                )
            )
    
    def _insert_decorators(
        self,
        conn,
        entity_id: int,
        annotations: List[str]
    ) -> None:
        """插入装饰器"""
        for annotation in annotations:
            name_id = self._get_or_create_name(annotation, conn)
            
            conn.execute(
                """
                INSERT INTO decorators (entity_id, name_id, arguments)
                VALUES (?, ?, ?)
                """,
                (entity_id, name_id, None)
            )
    
    def get_entity_by_id(self, entity_id: int) -> Optional[Dict]:
        """根据ID获取实体"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, n.name as entity_name, et.name as type_name
                FROM entities e
                JOIN names n ON e.name_id = n.id
                JOIN entity_types et ON e.type_id = et.id
                WHERE e.id = ?
                """,
                (entity_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
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
    
    def search_entities_by_name(self, name_pattern: str, limit: int = 100) -> List[Dict]:
        """按名称搜索实体"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, n.name as entity_name, et.name as type_name, f.path as file_path
                FROM entities e
                JOIN names n ON e.name_id = n.id
                JOIN entity_types et ON e.type_id = et.id
                JOIN files f ON e.file_id = f.id
                WHERE n.name LIKE ?
                LIMIT ?
                """,
                (f"%{name_pattern}%", limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def delete_entities_by_file(self, file_id: int) -> int:
        """删除文件的所有实体"""
        with self.pool.connection() as conn:
            # 先删除关联数据
            conn.execute(
                """
                DELETE FROM method_params 
                WHERE method_id IN (SELECT id FROM entities WHERE file_id = ?)
                """,
                (file_id,)
            )
            
            conn.execute(
                """
                DELETE FROM decorators 
                WHERE entity_id IN (SELECT id FROM entities WHERE file_id = ?)
                """,
                (file_id,)
            )
            
            # 删除实体
            cursor = conn.execute(
                "DELETE FROM entities WHERE file_id = ?",
                (file_id,)
            )
            
            conn.commit()
            return cursor.rowcount
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取实体统计"""
        with self.pool.connection() as conn:
            # 总数
            cursor = conn.execute("SELECT COUNT(*) FROM entities")
            total = cursor.fetchone()[0]
            
            # 按类型统计
            cursor = conn.execute(
                """
                SELECT et.name, COUNT(*) as count
                FROM entities e
                JOIN entity_types et ON e.type_id = et.id
                GROUP BY et.name
                """
            )
            by_type = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                "total_entities": total,
                "by_type": by_type
            }
