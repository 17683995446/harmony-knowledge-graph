"""
Application - FastAPI应用
创建和配置FastAPI应用实例
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.logger_manager import get_logger

logger = get_logger("web_application")

# 基于项目根目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")
    
    # 初始化数据库（延迟初始化，不会在导入时触发）
    from database.connection_pool import get_database_manager
    db_manager = get_database_manager()
    db_manager.initialize()
    
    logger.info("应用启动完成")
    
    yield
    
    # 关闭时清理
    logger.info("应用关闭中...")
    db_manager.get_pool().close_all()
    from web.api_routes import shutdown_thread_pool, cleanup_llm_client
    shutdown_thread_pool()
    cleanup_llm_client()
    logger.info("应用关闭完成")


def create_application() -> FastAPI:
    """创建FastAPI应用"""
    app = FastAPI(
        title="Harmony Knowledge Graph",
        description="百万行级ArkTS代码知识图谱系统",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # 配置CORS - allow_credentials=True时不能使用通配符origin
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 挂载静态文件（使用绝对路径）
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    
    # 注册路由
    from web.api_routes import api_router
    from web.page_routes import page_router
    
    app.include_router(api_router, prefix="/api")
    app.include_router(page_router)
    
    logger.info(f"FastAPI应用创建完成，静态目录: {STATIC_DIR}")
    
    return app


# 创建全局应用实例
app = create_application()
