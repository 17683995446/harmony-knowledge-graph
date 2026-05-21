"""
Logger Manager - 日志管理器
统一日志格式和输出，支持文件和控制台双输出
"""

import logging
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from rich.logging import RichHandler
from rich.console import Console


class LoggerManager:
    """日志管理器类"""
    
    _instance: Optional["LoggerManager"] = None
    _lock = threading.Lock()
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        name: str = "harmony_kg",
        level: str = "INFO",
        log_dir: str = "./logs",
        enable_file: bool = True,
        enable_console: bool = True
    ):
        if self._initialized:
            return
        
        self.name = name
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.log_dir = Path(log_dir)
        self.enable_file = enable_file
        self.enable_console = enable_console
        
        self._setup_logger()
        self._initialized = True
    
    def _setup_logger(self) -> None:
        """设置日志记录器"""
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(self.level)
        self.logger.handlers = []
        
        # 格式化器
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # 控制台处理器
        if self.enable_console:
            console_handler = RichHandler(
                console=Console(stderr=True),
                rich_tracebacks=True,
                show_time=False,
                show_path=False
            )
            console_handler.setLevel(self.level)
            self.logger.addHandler(console_handler)
        
        # 文件处理器
        if self.enable_file:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"{self.name}_{datetime.now():%Y%m%d}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(self.level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """获取日志记录器"""
        if name:
            return self.logger.getChild(name)
        return self.logger
    
    def debug(self, message: str, **kwargs) -> None:
        """调试日志"""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """信息日志"""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """警告日志"""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """错误日志"""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """严重错误日志"""
        self.logger.critical(message, **kwargs)


# 全局日志管理器实例
logger_manager = LoggerManager()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取日志记录器"""
    return logger_manager.get_logger(name)
