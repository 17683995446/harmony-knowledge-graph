"""
Query Executor - 查询执行器
执行SQL查询，支持自然语言到SQL的转换结果
"""

import json
import time
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

from database.connection_pool import ConnectionPool, get_database_manager
from core.logger_manager import get_logger

logger = get_logger("query_executor")


@dataclass
class QueryResult:
    """查询结果"""
    success: bool
    data: List[Dict]
    columns: List[str]
    execution_time_ms: float
    row_count: int
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "data": self.data,
            "columns": self.columns,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "row_count": self.row_count,
            "error_message": self.error_message
        }


class QueryExecutor:
    """查询执行器类"""
    
    # 允许的表（安全限制）
    ALLOWED_TABLES = {
        'files', 'entities', 'names', 'entity_types', 'type_names',
        'method_params', 'call_relations', 'inheritance_relations',
        'component_relations', 'import_relations', 'decorators',
        'code_metrics', 'entity_type_refs', 'search_index'
    }
    
    # 危险关键词（安全检查）
    DANGEROUS_KEYWORDS = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE',
        'TRUNCATE', 'GRANT', 'REVOKE', 'ATTACH', 'DETACH'
    ]
    
    def __init__(self, pool: Optional[ConnectionPool] = None):
        self.pool = pool or get_database_manager().get_pool()
    
    def validate_sql(self, sql: str) -> Tuple[bool, str]:
        """
        验证SQL安全性
        
        Returns:
            (是否安全, 错误信息)
        """
        sql_upper = sql.upper().strip()

        # 检查危险操作
        for keyword in self.DANGEROUS_KEYWORDS:
            if keyword in sql_upper:
                return False, f"检测到危险操作: {keyword}"

        # 只允许SELECT语句和WITH开头的CTE查询
        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            return False, "只允许执行SELECT查询"

        return True, ""
    
    def execute(
        self,
        sql: str,
        parameters: Tuple = (),
        validate: bool = True
    ) -> QueryResult:
        """
        执行SQL查询
        
        Args:
            sql: SQL语句
            parameters: 查询参数
            validate: 是否进行安全验证
            
        Returns:
            QueryResult: 查询结果
        """
        start_time = time.time()
        
        # 安全验证
        if validate:
            is_safe, error_msg = self.validate_sql(sql)
            if not is_safe:
                return QueryResult(
                    success=False,
                    data=[],
                    columns=[],
                    execution_time_ms=(time.time() - start_time) * 1000,
                    row_count=0,
                    error_message=error_msg
                )
        
        try:
            with self.pool.connection() as conn:
                cursor = conn.execute(sql, parameters)
                
                # 获取列名
                columns = [description[0] for description in cursor.description] if cursor.description else []
                
                # 获取数据
                rows = cursor.fetchall()
                data = [dict(row) for row in rows]
                
                execution_time = (time.time() - start_time) * 1000
                
                return QueryResult(
                    success=True,
                    data=data,
                    columns=columns,
                    execution_time_ms=execution_time,
                    row_count=len(data)
                )
                
        except Exception as e:
            logger.error(f"查询执行失败: {sql}, 错误: {e}")
            return QueryResult(
                success=False,
                data=[],
                columns=[],
                execution_time_ms=(time.time() - start_time) * 1000,
                row_count=0,
                error_message=str(e)
            )
    
    def execute_paginated(
        self,
        sql: str,
        parameters: Tuple = (),
        page: int = 1,
        page_size: int = 100
    ) -> QueryResult:
        """分页执行查询"""
        # 检查SQL是否已包含LIMIT，避免双重LIMIT
        sql_upper = sql.upper()
        if "ORDER BY" in sql_upper:
            has_limit = "LIMIT" in sql_upper.split("ORDER BY")[-1]
        else:
            has_limit = "LIMIT" in sql_upper

        if not has_limit:
            paginated_sql = f"{sql} LIMIT {page_size} OFFSET {(page - 1) * page_size}"
        else:
            paginated_sql = sql
        
        result = self.execute(paginated_sql, parameters)
        
        # 获取总数
        if result.success:
            count_sql = f"SELECT COUNT(*) as total FROM ({sql}) as subquery"
            count_result = self.execute(count_sql, parameters, validate=False)
            if count_result.success and count_result.data:
                result.row_count = count_result.data[0].get("total", 0)
        
        return result
    
    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        limit: int = 100
    ) -> QueryResult:
        """搜索实体"""
        base_sql = """
            SELECT 
                e.id,
                n.name as entity_name,
                et.name as entity_type,
                f.path as file_path,
                e.line_start,
                e.line_end
            FROM entities e
            JOIN names n ON e.name_id = n.id
            JOIN entity_types et ON e.type_id = et.id
            JOIN files f ON e.file_id = f.id
            WHERE n.name LIKE ?
        """
        
        params = [f"%{query}%"]
        
        if entity_type:
            base_sql += " AND et.name = ?"
            params.append(entity_type)
        
        base_sql += " ORDER BY n.name LIMIT ?"
        params.append(limit)
        
        return self.execute(base_sql, tuple(params), validate=False)
    
    def get_entity_details(self, entity_id: int) -> QueryResult:
        """获取实体详情"""
        sql = """
            SELECT 
                e.*,
                n.name as entity_name,
                et.name as entity_type,
                f.path as file_path
            FROM entities e
            JOIN names n ON e.name_id = n.id
            JOIN entity_types et ON e.type_id = et.id
            JOIN files f ON e.file_id = f.id
            WHERE e.id = ?
        """
        return self.execute(sql, (entity_id,), validate=False)
    
    def get_call_graph(self, entity_id: int, depth: int = 2) -> QueryResult:
        """获取调用图"""
        # 使用递归CTE获取调用链
        sql = """
            WITH RECURSIVE call_chain AS (
                -- 基础情况：直接调用
                SELECT 
                    cr.caller_id,
                    cr.callee_id,
                    1 as depth,
                    nc.name as caller_name,
                    nce.name as callee_name
                FROM call_relations cr
                JOIN entities ec ON cr.caller_id = ec.id
                JOIN entities ee ON cr.callee_id = ee.id
                JOIN names nc ON ec.name_id = nc.id
                JOIN names nce ON ee.name_id = nce.id
                WHERE cr.caller_id = ?
                
                UNION ALL
                
                -- 递归：被调用者继续调用
                SELECT 
                    cr.caller_id,
                    cr.callee_id,
                    cc.depth + 1,
                    nc.name as caller_name,
                    nce.name as callee_name
                FROM call_relations cr
                JOIN call_chain cc ON cr.caller_id = cc.callee_id
                JOIN entities ec ON cr.caller_id = ec.id
                JOIN entities ee ON cr.callee_id = ee.id
                JOIN names nc ON ec.name_id = nc.id
                JOIN names nce ON ee.name_id = nce.id
                WHERE cc.depth < ?
            )
            SELECT * FROM call_chain
            ORDER BY depth, caller_name
        """
        return self.execute(sql, (entity_id, depth), validate=False)
    
    def get_file_overview(self, file_path: Optional[str] = None) -> QueryResult:
        """获取文件概览"""
        if file_path:
            sql = """
                SELECT 
                    f.*,
                    COUNT(DISTINCT e.id) as entity_count,
                    GROUP_CONCAT(DISTINCT et.name) as entity_types
                FROM files f
                LEFT JOIN entities e ON f.id = e.file_id
                LEFT JOIN entity_types et ON e.type_id = et.id
                WHERE f.path LIKE ?
                GROUP BY f.id
            """
            return self.execute(sql, (f"%{file_path}%",), validate=False)
        else:
            sql = """
                SELECT 
                    f.*,
                    COUNT(DISTINCT e.id) as entity_count
                FROM files f
                LEFT JOIN entities e ON f.id = e.file_id
                GROUP BY f.id
                ORDER BY f.path
                LIMIT 100
            """
            return self.execute(sql, validate=False)
    
    def get_project_statistics(self) -> QueryResult:
        """获取项目统计"""
        sql = """
            SELECT 
                (SELECT COUNT(*) FROM files) as total_files,
                (SELECT COUNT(*) FROM entities) as total_entities,
                (SELECT COUNT(*) FROM call_relations) as total_calls,
                (SELECT COUNT(*) FROM inheritance_relations) as total_inheritance,
                (SELECT COUNT(DISTINCT et.name) FROM entities e JOIN entity_types et ON e.type_id = et.id) as entity_type_count
        """
        return self.execute(sql, validate=False)
    
    def get_entity_type_distribution(self) -> QueryResult:
        """获取实体类型分布"""
        sql = """
            SELECT 
                et.name as entity_type,
                COUNT(*) as count,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM entities), 2) as percentage
            FROM entities e
            JOIN entity_types et ON e.type_id = et.id
            GROUP BY et.name
            ORDER BY count DESC
        """
        return self.execute(sql, validate=False)
    
    def find_unused_entities(self) -> QueryResult:
        """查找未使用的实体"""
        sql = """
            SELECT 
                e.id,
                n.name as entity_name,
                et.name as entity_type,
                f.path as file_path
            FROM entities e
            JOIN names n ON e.name_id = n.id
            JOIN entity_types et ON e.type_id = et.id
            JOIN files f ON e.file_id = f.id
            LEFT JOIN call_relations cr ON e.id = cr.callee_id
            WHERE cr.callee_id IS NULL
              AND et.name IN ('method', 'function')
            ORDER BY f.path, n.name
            LIMIT 100
        """
        return self.execute(sql, validate=False)
    
    def find_duplicate_names(self) -> QueryResult:
        """查找重复名称"""
        sql = """
            SELECT 
                n.name,
                COUNT(*) as occurrence_count,
                GROUP_CONCAT(DISTINCT f.path) as files
            FROM entities e
            JOIN names n ON e.name_id = n.id
            JOIN files f ON e.file_id = f.id
            GROUP BY n.name
            HAVING COUNT(*) > 1
            ORDER BY occurrence_count DESC
            LIMIT 100
        """
        return self.execute(sql, validate=False)
    
    def get_complex_methods(self, min_complexity: int = 10) -> QueryResult:
        """获取复杂方法"""
        # 这里简化处理，实际应该基于控制流分析
        sql = """
            SELECT 
                e.id,
                n.name as method_name,
                f.path as file_path,
                e.line_end - e.line_start + 1 as line_count,
                (SELECT COUNT(*) FROM method_params WHERE method_id = e.id) as param_count
            FROM entities e
            JOIN names n ON e.name_id = n.id
            JOIN entity_types et ON e.type_id = et.id
            JOIN files f ON e.file_id = f.id
            WHERE et.name = 'method'
              AND (e.line_end - e.line_start + 1) > ?
            ORDER BY line_count DESC
            LIMIT 100
        """
        return self.execute(sql, (min_complexity,), validate=False)
