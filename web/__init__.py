"""
Web Module - Web模块
FastAPI Web应用，提供可视化界面和API
"""

from .application import create_application
from .api_routes import api_router
from .page_routes import page_router

__all__ = ["create_application", "api_router", "page_router"]
