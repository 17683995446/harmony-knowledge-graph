"""
Connection Pool - 数据库连接池
管理SQLite连接，支持并发访问
"""

import sqlite3
import threading
from queue import Queue, Empty
from typing import Optional, Dict, Any
from contextlib import contextmanager
from pathlib import Path

from core.logger_manager import get_logger

logger = get_logger("connection_pool")


class ConnectionPool:
    """SQLite连接池"""
    
    def __init__(
        self,
        db_path: str,
        max_connections: int = 10,
        timeout: float = 30.0
    ):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._connection_count = 0
        self._local = threading.local()
    
    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False
        )
        
        # 启用外键
        conn.execute("PRAGMA foreign_keys = ON")
        
        # 设置行工厂
        conn.row_factory = sqlite3.Row
        
        return conn
    
    def get_connection(self) -> sqlite3.Connection:
        """获取连接"""
        try:
            # 尝试从池中获取
            conn = self._pool.get(block=False)
            return conn
        except Empty:
            # 创建新连接
            with self._lock:
                if self._connection_count < self.max_connections:
                    self._connection_count += 1
                    return self._create_connection()
            
            # 等待可用连接
            try:
                return self._pool.get(block=True, timeout=self.timeout)
            except Empty:
                raise RuntimeError(f"连接池耗尽，无法获取连接 (max={self.max_connections})") from None
    
    def release_connection(self, conn: sqlite3.Connection) -> None:
        """释放连接回池"""
        if conn:
            try:
                self._pool.put(conn, block=False)
            except Exception:
                # 池已满，关闭连接
                conn.close()
                with self._lock:
                    self._connection_count -= 1
            # Clear thread-local reference so next get_connection() pulls from pool
            if hasattr(self._local, 'connection'):
                self._local.connection = None
    
    @contextmanager
    def connection(self):
        """连接上下文管理器"""
        conn = None
        try:
            conn = self.get_connection()
            yield conn
        finally:
            if conn:
                self.release_connection(conn)
    
    def execute(
        self,
        sql: str,
        parameters: tuple = (),
        fetch: bool = False
    ) -> Optional[list]:
        """执行SQL"""
        with self.connection() as conn:
            cursor = conn.execute(sql, parameters)
            if fetch:
                return cursor.fetchall()
            conn.commit()
            return None
    
    def executemany(
        self,
        sql: str,
        parameters_list: list
    ) -> int:
        """批量执行SQL"""
        with self.connection() as conn:
            cursor = conn.executemany(sql, parameters_list)
            conn.commit()
            return cursor.rowcount
    
    def close_all(self) -> None:
        """关闭所有连接"""
        # Close thread-local connections
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except Exception:
                pass
            self._local.connection = None
        
        while not self._pool.empty():
            try:
                conn = self._pool.get(block=False)
                conn.close()
            except Empty:
                break
        
        with self._lock:
            self._connection_count = 0
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


class DatabaseManager:
    """数据库管理器（延迟初始化）"""
    
    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = "./data/knowledge_graph.db"):
        if self._initialized:
            return
        
        self.db_path = db_path
        self.pool = ConnectionPool(db_path)
        self._initialized = True
    
    def initialize(self) -> None:
        """初始化数据库"""
        from database.schema_manager import SchemaManager
        
        schema_manager = SchemaManager(self.db_path)
        schema_manager.initialize_database()
    
    def get_pool(self) -> ConnectionPool:
        """获取连接池"""
        return self.pool
    
    def execute(self, sql: str, parameters: tuple = ()) -> Optional[list]:
        """执行SQL"""
        return self.pool.execute(sql, parameters, fetch=True)
    
    def execute_write(self, sql: str, parameters: tuple = ()) -> None:
        """执行写操作"""
        self.pool.execute(sql, parameters, fetch=False)
    
    def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[Dict]:
        """获取单行"""
        with self.pool.connection() as conn:
            cursor = conn.execute(sql, parameters)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def fetch_all(self, sql: str, parameters: tuple = ()) -> list:
        """获取所有行"""
        with self.pool.connection() as conn:
            cursor = conn.execute(sql, parameters)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


# 延迟初始化，避免导入时副作用
_db_manager: Optional[DatabaseManager] = None
_db_manager_lock = threading.Lock()


def get_database_manager(db_path: str = None) -> DatabaseManager:
    """获取数据库管理器（延迟初始化）"""
    global _db_manager
    if _db_manager is None:
        with _db_manager_lock:
            if _db_manager is None:
                if db_path is None:
                    from core.config_manager import get_configuration
                    config = get_configuration()
                    db_path = config.database_path
                _db_manager = DatabaseManager(db_path)
    return _db_manager
