"""
Configuration Manager - 配置管理器
统一管理所有配置项，支持环境变量和配置文件
"""

import os
import threading
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class ApplicationConfig(BaseSettings):
    """应用程序配置类"""
    
    # LLM配置
    silicon_flow_api_key: str = Field(
        default="",
        description="硅基流动API密钥"
    )
    silicon_flow_model: str = Field(
        default="Qwen2.5-7B-Instruct",
        description="硅基流动模型名称"
    )
    silicon_flow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        description="硅基流动API基础URL"
    )
    
    # 服务器配置
    host: str = Field(default="0.0.0.0", description="服务器监听地址")
    port: int = Field(default=8080, description="服务器端口")
    debug: bool = Field(default=False, description="调试模式")
    
    # 数据库配置
    database_path: str = Field(
        default="./data/knowledge_graph.db",
        description="SQLite数据库路径"
    )
    database_batch_size: int = Field(
        default=1000,
        description="数据库批量写入大小"
    )
    
    # 解析器配置
    parser_max_workers: int = Field(
        default=8,
        description="解析器最大工作进程数"
    )
    parser_chunk_size: int = Field(
        default=1000,
        description="解析器分块大小"
    )
    incremental_update: bool = Field(
        default=True,
        description="启用增量更新"
    )
    
    # 项目配置
    project_root: str = Field(
        default="./projects",
        description="项目根目录"
    )
    cache_dir: str = Field(
        default="./cache",
        description="缓存目录"
    )
    log_level: str = Field(default="INFO", description="日志级别")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    def ensure_directories(self) -> None:
        """确保必要目录存在"""
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.project_root).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
    
    @property
    def database_url(self) -> str:
        """获取数据库URL"""
        return f"sqlite:///{self.database_path}"
    
    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return not self.debug


# 延迟初始化，避免导入时副作用
_config_instance: Optional[ApplicationConfig] = None
_config_lock = threading.Lock()


def get_configuration() -> ApplicationConfig:
    """获取配置实例（延迟初始化）"""
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = ApplicationConfig()
                _config_instance.ensure_directories()
    return _config_instance
