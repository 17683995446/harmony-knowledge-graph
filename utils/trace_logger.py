"""
全链路日志追踪模块 - 用于深度测试系统行为
"""
import functools
import inspect
import logging
import time
import threading
from typing import Any, Callable

logger = logging.getLogger("trace")

# 线程本地存储，记录当前调用链
call_stack = threading.local()


def trace_call(func: Callable) -> Callable:
    """
    函数调用追踪装饰器 - 在函数入口和出口打印详细日志
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 获取调用信息
        func_name = func.__qualname__
        thread_id = threading.current_thread().ident
        
        # 初始化调用栈
        if not hasattr(call_stack, 'depth'):
            call_stack.depth = 0
            call_stack.chain = []
        
        # 记录调用开始
        call_stack.depth += 1
        indent = "  " * (call_stack.depth - 1)
        
        # 构建参数信息（避免过长）
        args_str = _format_args(args, kwargs)
        
        logger.info(f"[TRACE][T{thread_id}]{indent}▶️  ENTER {func_name}({args_str})")
        
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = (time.time() - start_time) * 1000
            
            # 格式化返回值
            result_str = _format_result(result)
            logger.info(f"[TRACE][T{thread_id}]{indent}✅  EXIT  {func_name} -> {result_str} ({elapsed:.2f}ms)")
            
            return result
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"[TRACE][T{thread_id}]{indent}❌  ERROR {func_name}: {type(e).__name__}: {str(e)} ({elapsed:.2f}ms)")
            raise
        finally:
            call_stack.depth -= 1
    
    return wrapper


def trace_line(message: str, level: str = "debug"):
    """
    行级追踪 - 在代码特定位置打印日志
    """
    thread_id = threading.current_thread().ident
    depth = getattr(call_stack, 'depth', 0)
    indent = "  " * depth
    
    log_func = getattr(logger, level)
    log_func(f"[LINE][T{thread_id}]{indent}📍  {message}")


def _format_args(args: tuple, kwargs: dict) -> str:
    """格式化参数，避免过长"""
    parts = []
    
    for arg in args[:3]:  # 最多显示3个位置参数
        parts.append(_format_value(arg))
    
    for k, v in list(kwargs.items())[:3]:  # 最多显示3个关键字参数
        parts.append(f"{k}={_format_value(v)}")
    
    if len(args) > 3 or len(kwargs) > 3:
        parts.append("...")
    
    return ", ".join(parts)


def _format_value(value: Any) -> str:
    """格式化单个值"""
    if value is None:
        return "None"
    elif isinstance(value, str):
        if len(value) > 30:
            return f"'{value[:27]}...'"
        return f"'{value}'"
    elif isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    elif isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    elif hasattr(value, '__class__'):
        return f"<{value.__class__.__name__}>"
    else:
        return str(value)


def _format_result(result: Any) -> str:
    """格式化返回值"""
    if result is None:
        return "None"
    elif isinstance(result, bool):
        return str(result)
    elif isinstance(result, int):
        return str(result)
    elif isinstance(result, str):
        if len(result) > 30:
            return f"'{result[:27]}...'"
        return f"'{result}'"
    elif isinstance(result, (list, tuple)):
        return f"[{len(result)} items]"
    elif isinstance(result, dict):
        return f"{{{len(result)} keys}}"
    else:
        return f"<{result.__class__.__name__}>"


class TraceContext:
    """上下文管理器，用于追踪代码块"""
    
    def __init__(self, name: str):
        self.name = name
        self.start_time = None
        self.thread_id = threading.current_thread().ident
    
    def __enter__(self):
        depth = getattr(call_stack, 'depth', 0)
        indent = "  " * depth
        logger.info(f"[BLOCK][T{self.thread_id}]{indent}▶️  BEGIN {self.name}")
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.time() - self.start_time) * 1000
        depth = getattr(call_stack, 'depth', 0)
        indent = "  " * depth
        
        if exc_type:
            logger.error(f"[BLOCK][T{self.thread_id}]{indent}❌  FAIL  {self.name}: {exc_type.__name__} ({elapsed:.2f}ms)")
        else:
            logger.info(f"[BLOCK][T{self.thread_id}]{indent}✅  END   {self.name} ({elapsed:.2f}ms)")
        
        return False  # 不吞掉异常
