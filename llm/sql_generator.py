"""
SQL Generator - SQL生成器
基于数据库模式生成SQL查询
"""

import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from llm.silicon_flow_client import SiliconFlowClient
from core.logger_manager import get_logger

logger = get_logger("sql_generator")


@dataclass
class SchemaContext:
    """数据库模式上下文"""
    tables: Dict[str, Dict[str, str]] = field(default_factory=dict)
    relationships: List[Dict] = field(default_factory=list)
    examples: List[Dict] = field(default_factory=list)
    
    def to_string(self) -> str:
        """转换为字符串表示"""
        lines = []
        
        # 表结构
        lines.append("表结构:")
        for table_name, columns in self.tables.items():
            lines.append(f"\n{table_name}:")
            for col_name, col_type in columns.items():
                lines.append(f"  - {col_name}: {col_type}")
        
        # 关系
        if self.relationships:
            lines.append("\n表关系:")
            for rel in self.relationships:
                lines.append(f"  - {rel['from']} -> {rel['to']}: {rel['type']}")
        
        return '\n'.join(lines)


class SQLGenerator:
    """SQL生成器类"""
    
    # 预定义的查询示例
    DEFAULT_EXAMPLES = [
        {
            "question": "查找所有名为MainPage的类",
            "sql": "SELECT e.id, n.name, f.path FROM entities e JOIN names n ON e.name_id = n.id JOIN files f ON e.file_id = f.id JOIN entity_types et ON e.type_id = et.id WHERE n.name = 'MainPage' AND et.name = 'class'"
        },
        {
            "question": "统计每个文件的实体数量",
            "sql": "SELECT f.path, COUNT(e.id) as entity_count FROM files f LEFT JOIN entities e ON f.id = e.file_id GROUP BY f.id ORDER BY entity_count DESC"
        },
        {
            "question": "查找调用了fetchData方法的所有方法",
            "sql": "SELECT DISTINCT nc.name as caller_name, f.path FROM call_relations cr JOIN entities ec ON cr.caller_id = ec.id JOIN names nc ON ec.name_id = nc.id JOIN files f ON ec.file_id = f.id JOIN entities ee ON cr.callee_id = ee.id JOIN names ne ON ee.name_id = ne.id WHERE ne.name = 'fetchData'"
        },
        {
            "question": "查找所有组件类",
            "sql": "SELECT e.id, n.name, f.path FROM entities e JOIN names n ON e.name_id = n.id JOIN files f ON e.file_id = f.id JOIN entity_types et ON e.type_id = et.id WHERE et.name = 'component'"
        },
        {
            "question": "查找包含@Entry装饰器的类",
            "sql": "SELECT DISTINCT e.id, n.name, f.path FROM entities e JOIN names n ON e.name_id = n.id JOIN files f ON e.file_id = f.id JOIN decorators d ON e.id = d.entity_id JOIN names nd ON d.name_id = nd.id WHERE nd.name = 'Entry'"
        }
    ]
    
    def __init__(
        self,
        llm_client: Optional[SiliconFlowClient] = None,
        schema_context: Optional[SchemaContext] = None
    ):
        self.llm_client = llm_client or SiliconFlowClient()
        self.schema_context = schema_context or self._build_default_schema()
    
    def _build_default_schema(self) -> SchemaContext:
        """构建默认数据库模式"""
        schema = SchemaContext()
        
        # 定义表结构
        schema.tables = {
            "files": {
                "id": "INTEGER PRIMARY KEY",
                "path": "TEXT",
                "hash": "BLOB",
                "size": "INTEGER",
                "modified_time": "REAL"
            },
            "entities": {
                "id": "INTEGER PRIMARY KEY",
                "name_id": "INTEGER -> names.id",
                "type_id": "INTEGER -> entity_types.id",
                "file_id": "INTEGER -> files.id",
                "parent_id": "INTEGER -> entities.id",
                "line_start": "INTEGER",
                "line_end": "INTEGER",
                "flags": "INTEGER"
            },
            "names": {
                "id": "INTEGER PRIMARY KEY",
                "name": "TEXT",
                "hash": "INTEGER"
            },
            "entity_types": {
                "id": "INTEGER PRIMARY KEY",
                "name": "TEXT"  # class, method, function, component, etc.
            },
            "call_relations": {
                "caller_id": "INTEGER -> entities.id",
                "callee_id": "INTEGER -> entities.id",
                "call_count": "INTEGER"
            },
            "inheritance_relations": {
                "child_id": "INTEGER -> entities.id",
                "parent_id": "INTEGER -> entities.id",
                "relation_type": "INTEGER"  # 1=extends, 2=implements
            },
            "component_relations": {
                "parent_id": "INTEGER -> entities.id",
                "child_id": "INTEGER -> entities.id"
            },
            "decorators": {
                "id": "INTEGER PRIMARY KEY",
                "entity_id": "INTEGER -> entities.id",
                "name_id": "INTEGER -> names.id",
                "arguments": "TEXT"
            }
        }
        
        # 定义关系
        schema.relationships = [
            {"from": "entities", "to": "names", "type": "name_id", "description": "实体名称"},
            {"from": "entities", "to": "files", "type": "file_id", "description": "所属文件"},
            {"from": "entities", "to": "entity_types", "type": "type_id", "description": "实体类型"},
            {"from": "call_relations", "to": "entities", "type": "caller_id/callee_id", "description": "调用关系"},
            {"from": "decorators", "to": "entities", "type": "entity_id", "description": "装饰器"}
        ]
        
        schema.examples = self.DEFAULT_EXAMPLES
        
        return schema
    
    async def generate_sql(self, natural_language: str) -> Dict[str, Any]:
        """
        生成SQL查询
        
        Args:
            natural_language: 自然语言查询
            
        Returns:
            Dict: 包含sql、explanation等字段
        """
        try:
            sql = await self.llm_client.generate_sql(
                natural_language=natural_language,
                schema_context=self.schema_context.to_string(),
                examples=self.schema_context.examples
            )

            if not sql or not sql.strip():
                return {
                    "success": False,
                    "sql": "",
                    "natural_language": natural_language,
                    "error": "AI未能生成有效的SQL查询"
                }

            return {
                "success": True,
                "sql": sql,
                "natural_language": natural_language,
                "explanation": None  # 可以后续添加解释
            }
            
        except Exception as e:
            logger.error(f"SQL生成失败: {e}")
            return {
                "success": False,
                "sql": None,
                "natural_language": natural_language,
                "error": str(e)
            }

    def get_common_queries(self) -> List[Dict[str, str]]:
        """获取常用查询模板"""
        return [
            {
                "name": "查找类定义",
                "description": "搜索特定名称的类",
                "sql": "SELECT e.id, n.name, f.path, e.line_start FROM entities e JOIN names n ON e.name_id = n.id JOIN files f ON e.file_id = f.id JOIN entity_types et ON e.type_id = et.id WHERE et.name = 'class' AND n.name LIKE '%关键词%'"
            },
            {
                "name": "查找方法调用",
                "description": "查找所有调用特定方法的地方",
                "sql": "SELECT nc.name as caller, ne.name as callee, f.path FROM call_relations cr JOIN entities ec ON cr.caller_id = ec.id JOIN names nc ON ec.name_id = nc.id JOIN entities ee ON cr.callee_id = ee.id JOIN names ne ON ee.name_id = ne.id JOIN files f ON ec.file_id = f.id WHERE ne.name = '方法名'"
            },
            {
                "name": "统计文件复杂度",
                "description": "按实体数量排序文件",
                "sql": "SELECT f.path, COUNT(e.id) as entity_count FROM files f LEFT JOIN entities e ON f.id = e.file_id GROUP BY f.id ORDER BY entity_count DESC LIMIT 20"
            },
            {
                "name": "查找未使用方法",
                "description": "找出没有被调用的方法",
                "sql": "SELECT n.name, f.path FROM entities e JOIN names n ON e.name_id = n.id JOIN files f ON e.file_id = f.id JOIN entity_types et ON e.type_id = et.id LEFT JOIN call_relations cr ON e.id = cr.callee_id WHERE et.name = 'method' AND cr.callee_id IS NULL"
            },
            {
                "name": "查找继承链",
                "description": "查找类的继承关系",
                "sql": "SELECT nc.name as child, np.name as parent FROM inheritance_relations ir JOIN entities ec ON ir.child_id = ec.id JOIN names nc ON ec.name_id = nc.id JOIN entities ep ON ir.parent_id = ep.id JOIN names np ON ep.name_id = np.id WHERE nc.name = '类名'"
            },
            {
                "name": "查找组件树",
                "description": "查找UI组件的层次结构",
                "sql": "SELECT np.name as parent, nc.name as child FROM component_relations cr JOIN entities ep ON cr.parent_id = ep.id JOIN names np ON ep.name_id = np.id JOIN entities ec ON cr.child_id = ec.id JOIN names nc ON ec.name_id = nc.id"
            },
            {
                "name": "查找装饰器使用",
                "description": "查找使用特定装饰器的实体",
                "sql": "SELECT n.name, nd.name as decorator, f.path FROM decorators d JOIN entities e ON d.entity_id = e.id JOIN names n ON e.name_id = n.id JOIN names nd ON d.name_id = nd.id JOIN files f ON e.file_id = f.id WHERE nd.name = '装饰器名'"
            },
            {
                "name": "文件依赖分析",
                "description": "分析文件间的导入关系",
                "sql": "SELECT f.path as importer, fi.path as imported FROM import_relations ir JOIN files f ON ir.file_id = f.id LEFT JOIN files fi ON ir.imported_file_id = fi.id"
            }
        ]
    
    async def suggest_queries(self, keyword: str) -> List[Dict[str, str]]:
        """
        根据关键词建议查询
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            建议的查询列表
        """
        common_queries = self.get_common_queries()
        
        # 简单的关键词匹配
        suggestions = []
        keyword_lower = keyword.lower()
        
        for query in common_queries:
            if (keyword_lower in query["name"].lower() or 
                keyword_lower in query["description"].lower()):
                suggestions.append(query)
        
        return suggestions[:5]
