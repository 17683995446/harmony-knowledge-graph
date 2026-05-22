"""
API Routes - API路由
RESTful API端点定义
"""

import time
import copy
import asyncio
import threading
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from database.query_executor import QueryExecutor, QueryResult
from database.entity_repository import EntityRepository
from database.relation_repository import RelationRepository
from database.connection_pool import get_database_manager
from database.schema_manager import SchemaManager
from llm.sql_generator import SQLGenerator
from llm.silicon_flow_client import SiliconFlowClient
from core.logger_manager import get_logger
from core.config_manager import get_configuration

logger = get_logger("api_routes")
api_router = APIRouter()

# 线程池，用于执行阻塞操作
_thread_pool = ThreadPoolExecutor(max_workers=4)


def cleanup_llm_client() -> None:
    """关闭LLM客户端，释放httpx.AsyncClient资源（同步包装）"""
    global _sql_generator, _llm_client
    if _llm_client is not None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建一个新线程来执行异步关闭
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _llm_client.close())
                    future.result()
            else:
                loop.run_until_complete(_llm_client.close())
        except RuntimeError:
            asyncio.run(_llm_client.close())
        _llm_client = None
        _sql_generator = None


def shutdown_thread_pool() -> None:
    """关闭线程池，释放线程资源"""
    global _thread_pool
    if _thread_pool is not None:
        _thread_pool.shutdown(wait=True)
        _thread_pool = None

# 扫描状态锁，防止并发启动扫描
_scan_lock = threading.Lock()

# SQL生成器锁，防止并发创建实例
_generator_lock = threading.Lock()

# Pydantic模型
class NaturalLanguageQuery(BaseModel):
    question: str = Field(..., max_length=2000, description="自然语言问题")
    use_cache: bool = True

class SQLQuery(BaseModel):
    sql: str = Field(..., max_length=10000, description="SQL查询语句")
    parameters: List[Any] = []

class ScanRequest(BaseModel):
    project_path: str
    incremental: bool = True

class ScanStatus(BaseModel):
    status: str
    progress: float
    message: str

# 全局服务实例
_sql_generator: Optional[SQLGenerator] = None
_llm_client: Optional[SiliconFlowClient] = None


def get_sql_generator() -> SQLGenerator:
    """获取SQL生成器实例（线程安全）"""
    global _sql_generator, _llm_client
    with _generator_lock:
        if _sql_generator is None:
            _llm_client = SiliconFlowClient()
            _sql_generator = SQLGenerator(llm_client=_llm_client)
    return _sql_generator


# ==================== 查询API ====================

@api_router.post("/query/natural-language")
async def query_natural_language(query: NaturalLanguageQuery) -> Dict:
    """
    自然语言查询 - 将自然语言问题转换为SQL并执行
    """
    try:
        generator = get_sql_generator()
        
        # 直接await异步方法，避免嵌套事件循环
        sql_result = await generator.generate_sql(query.question)
        
        if not sql_result["success"]:
            raise HTTPException(status_code=400, detail=sql_result.get("error", "SQL生成失败"))
        
        sql = sql_result["sql"]
        
        # 验证AI生成的SQL安全性
        executor = QueryExecutor()
        is_safe, error_msg = executor.validate_sql(sql)
        if not is_safe:
            raise HTTPException(status_code=400, detail=f"AI生成的SQL不安全: {error_msg}")

        # 执行SQL
        query_result = executor.execute(sql)
        
        return {
            "success": True,
            "question": query.question,
            "generated_sql": sql,
            "results": query_result.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自然语言查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/query/sql")
async def query_sql(query: SQLQuery) -> Dict:
    """直接执行SQL查询（限制最大返回10000行）"""
    try:
        executor = QueryExecutor()
        # Add LIMIT if not present to prevent resource exhaustion
        sql = query.sql.strip()
        sql_upper = sql.upper()
        if "LIMIT" not in sql_upper:
            sql = f"{sql} LIMIT 10000"
        result = executor.execute(sql, tuple(query.parameters))
        return result.to_dict()
    except Exception as e:
        logger.error(f"SQL查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/query/suggestions")
async def get_query_suggestions(keyword: str = Query(..., description="搜索关键词")) -> List[Dict]:
    """获取查询建议"""
    try:
        generator = get_sql_generator()
        # 直接await异步方法，避免嵌套事件循环
        suggestions = await generator.suggest_queries(keyword)
        return suggestions
    except Exception as e:
        logger.error(f"获取查询建议失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/query/common")
async def get_common_queries() -> List[Dict]:
    """获取常用查询模板"""
    try:
        generator = get_sql_generator()
        return generator.get_common_queries()
    except Exception as e:
        logger.error(f"获取常用查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 实体API ====================

@api_router.get("/entities/search")
async def search_entities(
    q: str = Query(..., description="搜索关键词"),
    type: Optional[str] = Query(None, description="实体类型"),
    limit: int = Query(100, ge=1, le=10000, description="返回数量限制")
) -> Dict:
    """根据名称搜索代码实体"""
    try:
        executor = QueryExecutor()
        result = executor.search_entities(q, type, limit)
        return result.to_dict()
    except Exception as e:
        logger.error(f"搜索实体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/entities/{entity_id}")
async def get_entity(entity_id: int) -> Dict:
    """获取指定ID的实体详细信息"""
    try:
        executor = QueryExecutor()
        result = executor.get_entity_details(entity_id)
        
        if not result.success or not result.data:
            raise HTTPException(status_code=404, detail="实体不存在")
        
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/entities/{entity_id}/calls")
async def get_entity_calls(entity_id: int) -> Dict:
    """获取指定实体的调用图"""
    try:
        executor = QueryExecutor()
        result = executor.get_call_graph(entity_id)
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取调用关系失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 文件API ====================

@api_router.get("/files")
async def get_files(
    path: Optional[str] = Query(None, description="文件路径过滤"),
    limit: int = Query(100, ge=1, le=10000, description="返回数量限制")
) -> Dict:
    """获取项目中的文件列表"""
    try:
        executor = QueryExecutor()
        result = executor.get_file_overview(path)
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/files/{file_id}/entities")
async def get_file_entities(file_id: int) -> Dict:
    """获取指定文件中的所有实体"""
    try:
        repo = EntityRepository()
        entities = repo.get_entities_by_file(file_id)
        return {
            "success": True,
            "file_id": file_id,
            "entities": entities
        }
    except Exception as e:
        logger.error(f"获取文件实体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 统计API ====================

@api_router.get("/statistics/overview")
async def get_statistics_overview() -> Dict:
    """获取项目整体统计信息"""
    try:
        executor = QueryExecutor()
        result = executor.get_project_statistics()
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取统计概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/statistics/entity-types")
async def get_entity_type_distribution() -> Dict:
    """获取各类型实体的数量分布"""
    try:
        executor = QueryExecutor()
        result = executor.get_entity_type_distribution()
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取实体类型分布失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/statistics/unused-entities")
async def get_unused_entities() -> Dict:
    """查找没有被调用的方法"""
    try:
        executor = QueryExecutor()
        result = executor.find_unused_entities()
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取未使用实体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/statistics/duplicates")
async def get_duplicate_names() -> Dict:
    """查找项目中重复定义的实体名称"""
    try:
        executor = QueryExecutor()
        result = executor.find_duplicate_names()
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取重复名称失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/statistics/complex-methods")
async def get_complex_methods(min_complexity: int = Query(10, description="最小复杂度")) -> Dict:
    """查找代码行数较多的方法"""
    try:
        executor = QueryExecutor()
        result = executor.get_complex_methods(min_complexity)
        return result.to_dict()
    except Exception as e:
        logger.error(f"获取复杂方法失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 图谱API ====================

@api_router.get("/graph/dependency")
async def get_dependency_graph(
    entity_id: Optional[int] = Query(None, description="中心实体ID"),
    depth: int = Query(2, ge=1, le=10, description="遍历深度")
) -> Dict:
    """获取代码实体的依赖关系图"""
    try:
        repo = RelationRepository()
        
        if entity_id:
            callees = repo.get_callees(entity_id)
            callers = repo.get_callers(entity_id)
            return {
                "success": True,
                "entity_id": entity_id,
                "callees": callees,
                "callers": callers
            }
        else:
            calls = repo.get_call_graph()
            return {
                "success": True,
                "calls": calls[:1000]
            }
    except Exception as e:
        logger.error(f"获取依赖图谱失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/graph/inheritance")
async def get_inheritance_graph(
    entity_id: Optional[int] = Query(None, description="实体ID，不传则返回全部")
) -> Dict:
    """获取类的继承关系链"""
    try:
        repo = RelationRepository()
        
        if entity_id:
            chain = repo.get_inheritance_chain(entity_id)
            subclasses = repo.get_subclasses(entity_id)
            return {
                "success": True,
                "entity_id": entity_id,
                "inheritance_chain": chain,
                "subclasses": subclasses
            }
        else:
            # 返回所有继承关系
            db = get_database_manager()
            rows = db.fetch_all(
                """SELECT ir.child_id, ir.parent_id, ir.relation_type,
                          nc.name as child_name, np.name as parent_name
                   FROM inheritance_relations ir
                   JOIN entities ec ON ir.child_id = ec.id
                   JOIN names nc ON ec.name_id = nc.id
                   JOIN entities ep ON ir.parent_id = ep.id
                   JOIN names np ON ep.name_id = np.id
                   LIMIT 500"""
            )
            return {"success": True, "relations": rows}
    except Exception as e:
        logger.error(f"获取继承图谱失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/graph/call")
async def get_call_graph(
    entity_id: Optional[int] = Query(None, description="中心实体ID"),
    depth: int = Query(2, ge=1, le=10, description="遍历深度")
) -> Dict:
    """获取方法调用关系图"""
    try:
        repo = RelationRepository()
        
        if entity_id:
            callees = repo.get_callees(entity_id)
            callers = repo.get_callers(entity_id)
            return {
                "success": True,
                "entity_id": entity_id,
                "callees": callees,
                "callers": callers
            }
        else:
            calls = repo.get_call_graph()
            return {
                "success": True,
                "calls": calls[:1000]
            }
    except Exception as e:
        logger.error(f"获取调用图谱失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/graph/component")
async def get_component_graph() -> Dict:
    """获取UI组件层次结构"""
    try:
        db = get_database_manager()
        rows = db.fetch_all(
            """SELECT cr.parent_id, cr.child_id, cr.relation_type,
                      np.name as parent_name, nc.name as child_name
               FROM component_relations cr
               JOIN entities ep ON cr.parent_id = ep.id
               JOIN names np ON ep.name_id = np.id
               JOIN entities ec ON cr.child_id = ec.id
               JOIN names nc ON ec.name_id = nc.id
               LIMIT 500"""
        )
        return {"success": True, "relations": rows}
    except Exception as e:
        logger.error(f"获取组件图谱失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 扫描API ====================

scan_status = {
    "is_scanning": False,
    "progress": 0.0,
    "message": "",
    "last_scan": None,
    "scanned_files": 0,
    "parsed_entities": 0,
    "found_relations": 0,
    "duration": 0.0,
    "error": None
}


@api_router.post("/scan/start")
async def start_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks
) -> Dict:
    """启动后台任务扫描项目代码"""
    global scan_status
    
    if scan_status["is_scanning"]:
        raise HTTPException(status_code=409, detail="扫描已在进行中")
    
    import os
    if not os.path.isdir(request.project_path):
        raise HTTPException(status_code=400, detail=f"项目路径不存在: {request.project_path}")
    
    with _scan_lock:
        if scan_status["is_scanning"]:
            raise HTTPException(status_code=409, detail="扫描已在进行中")
        scan_status["is_scanning"] = True
        scan_status["progress"] = 0.0
        scan_status["message"] = "准备扫描..."
        scan_status["error"] = None
        scan_status["scanned_files"] = 0
        scan_status["parsed_entities"] = 0
        scan_status["found_relations"] = 0
        scan_status["duration"] = 0.0
    
    # 使用同步函数，让FastAPI自动放到线程池执行，避免阻塞事件循环
    background_tasks.add_task(
        perform_scan,
        request.project_path,
        request.incremental
    )
    
    return {
        "success": True,
        "message": "扫描任务已启动"
    }


@api_router.get("/scan/status")
async def get_scan_status() -> Dict:
    """获取当前扫描任务的进度"""
    return copy.deepcopy(scan_status)


def perform_scan(project_path: str, incremental: bool) -> None:
    """
    执行扫描任务（同步函数，在线程池中运行）
    """
    global scan_status
    start_time = time.time()
    
    try:
        from core.pipeline_manager import PipelineManager
        
        scan_status["message"] = "初始化扫描器..."
        scan_status["progress"] = 0.05
        
        pipeline = PipelineManager(
            project_path=project_path,
            max_workers=None
        )
        
        scan_status["message"] = "扫描文件中..."
        scan_status["progress"] = 0.15
        
        result = pipeline.run_full_pipeline(incremental=incremental)
        
        duration = time.time() - start_time
        
        if result.success:
            scan_status["progress"] = 1.0
            scan_status["message"] = "扫描完成"
            scan_status["scanned_files"] = result.scanned_files
            scan_status["parsed_entities"] = result.parsed_entities
            scan_status["found_relations"] = result.found_relations
            scan_status["duration"] = round(duration, 2)
            scan_status["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S")
            scan_status["error"] = None
            logger.info(f"扫描完成: 文件={result.scanned_files}, 实体={result.parsed_entities}, 耗时={duration:.1f}s")
        else:
            scan_status["message"] = f"扫描失败: {result.error}"
            scan_status["error"] = result.error
            logger.error(f"扫描失败: {result.error}")
        
    except Exception as e:
        logger.error(f"扫描异常: {e}", exc_info=True)
        scan_status["message"] = f"扫描失败: {str(e)}"
        scan_status["error"] = str(e)
    finally:
        scan_status["is_scanning"] = False
        if scan_status["progress"] < 1.0:
            scan_status["progress"] = 0.0


@api_router.post("/database/reset")
async def reset_database(confirm: bool = Query(False, description="确认重置（必须为true）")) -> Dict:
    """清空并重建数据库"""
    if not confirm:
        raise HTTPException(status_code=400, detail="请添加 ?confirm=true 参数确认重置操作")
    try:
        config = get_configuration()
        schema_manager = SchemaManager(config.database_path)
        schema_manager.reset_database()
        return {"success": True, "message": "数据库已重置"}
    except Exception as e:
        logger.error(f"重置数据库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 系统API ====================

@api_router.get("/health")
async def health_check() -> Dict:
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0"
    }


@api_router.get("/config")
async def get_config() -> Dict:
    """获取系统配置信息（敏感信息已脱敏）"""
    config = get_configuration()
    return {
        "model": config.silicon_flow_model,
        "max_workers": config.parser_max_workers,
        "incremental_update": config.incremental_update
    }
