"""
Page Routes - 页面路由
HTML页面路由定义
"""

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

page_router = APIRouter()

# 基于项目根目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# 手动创建Jinja2环境，避免Starlette的缓存bug
_jinja_env = Environment(
    loader=FileSystemLoader(str(STATIC_DIR)),
    autoescape=select_autoescape(default=True),
    enable_async=False
)


def _render_template(template_name: str, context: dict) -> str:
    """渲染Jinja2模板"""
    # 防止路径遍历攻击
    if ".." in template_name or "/" in template_name or "\\" in template_name:
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>400 - Bad Request</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
<h1>400 - Bad Request</h1>
<p>Invalid template name.</p>
</body>
</html>"""
    try:
        template = _jinja_env.get_template(template_name)
        return template.render(**context)
    except TemplateNotFound:
        import html
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>404 - Template Not Found</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
<h1>404 - Page Not Found</h1>
<p>The template <strong>{html.escape(template_name)}</strong> does not exist.</p>
<p>Please ensure the static files are properly deployed.</p>
</body>
</html>"""


@page_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    html = _render_template("index.html", {"request": request})
    return HTMLResponse(content=html)


@page_router.get("/query", response_class=HTMLResponse)
async def query_page(request: Request):
    """查询页面"""
    html = _render_template("query.html", {"request": request})
    return HTMLResponse(content=html)


@page_router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    """图谱页面"""
    html = _render_template("graph.html", {"request": request})
    return HTMLResponse(content=html)


@page_router.get("/statistics", response_class=HTMLResponse)
async def statistics_page(request: Request):
    """统计页面"""
    html = _render_template("statistics.html", {"request": request})
    return HTMLResponse(content=html)


@page_router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    """扫描页面"""
    html = _render_template("scan.html", {"request": request})
    return HTMLResponse(content=html)
