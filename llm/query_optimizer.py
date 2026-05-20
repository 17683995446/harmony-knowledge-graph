"""
Query Optimizer - 查询优化器
优化SQL查询性能，添加缓存机制
"""

import asyncio
import hashlib
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from functools import wraps
from collections import OrderedDict

from core.logger_manager import get_logger

logger = get_logger("query_optimizer")


@dataclass
class CachedResult:
    """缓存结果"""
    data: Any
    timestamp: float
    query_hash: str
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > ttl_seconds


class LRUCache:
    """LRU缓存"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: OrderedDict[str, CachedResult] = OrderedDict()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        """获取缓存值"""
        if key in self.cache:
            cached = self.cache[key]
            if not cached.is_expired(ttl_seconds):
                # 移动到末尾（最近使用）
                self.cache.move_to_end(key)
                self.hits += 1
                return cached.data
            else:
                # 过期，删除
                del self.cache[key]
        
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        # 如果已满，删除最旧的
        if len(self.cache) >= self.max_size and key not in self.cache:
            self.cache.popitem(last=False)
        
        self.cache[key] = CachedResult(
            data=value,
            timestamp=time.time(),
            query_hash=key
        )
        self.cache.move_to_end(key)
    
    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(hit_rate, 2)
        }


class QueryOptimizer:
    """查询优化器"""
    
    def __init__(self, cache_size: int = 100, default_ttl: int = 300):
        self.cache = LRUCache(max_size=cache_size)
        self.default_ttl = default_ttl
        self.query_stats: Dict[str, Dict] = {}
    
    def _hash_query(self, sql: str, params: tuple = ()) -> str:
        """生成查询哈希"""
        query_str = f"{sql}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(query_str.encode()).hexdigest()
    
    def optimize_sql(self, sql: str) -> str:
        """
        优化SQL查询
        
        Args:
            sql: 原始SQL
            
        Returns:
            str: 优化后的SQL
        """
        optimized = sql.strip()
        
        # 添加LIMIT如果没有
        # 检查主查询（最后一个右括号之后）是否已有LIMIT，避免破坏子查询中的LIMIT
        main_query = sql
        last_paren = sql.rfind(')')
        if last_paren != -1:
            main_query = sql[last_paren+1:]
        if "LIMIT" not in main_query.upper():
            # 检查是否是聚合查询
            if "COUNT(" not in optimized.upper():
                optimized += " LIMIT 1000"
        
        # 优化SELECT *
        if "SELECT *" in optimized.upper():
            # 保留原样，但记录警告
            logger.warning("查询使用SELECT *，建议指定具体列")
        
        return optimized
    
    def cached_query(
        self,
        ttl_seconds: Optional[int] = None
    ) -> Callable:
        """
        查询缓存装饰器
        
        Args:
            ttl_seconds: 缓存时间（秒）
            
        Returns:
            装饰器函数
        """
        ttl = ttl_seconds or self.default_ttl
        
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                # 生成缓存键
                cache_key = self._hash_query(
                    str(args),
                    tuple(sorted(kwargs.items()))
                )
                
                # 尝试从缓存获取
                cached = self.cache.get(cache_key, ttl)
                if cached is not None:
                    return cached
                
                # 执行查询
                result = func(*args, **kwargs)
                
                # 缓存结果
                self.cache.set(cache_key, result)
                
                return result
            
            return wrapper
        return decorator
    
    async def execute_with_cache(
        self,
        executor: Callable,
        sql: str,
        params: tuple = (),
        ttl_seconds: Optional[int] = None
    ) -> Any:
        """
        带缓存的执行
        
        Args:
            executor: 执行函数
            sql: SQL语句
            params: 查询参数
            ttl_seconds: 缓存时间
            
        Returns:
            查询结果
        """
        ttl = ttl_seconds or self.default_ttl
        cache_key = self._hash_query(sql, params)
        
        # 尝试从缓存获取
        cached = self.cache.get(cache_key, ttl)
        if cached is not None:
            logger.debug(f"缓存命中: {sql[:50]}...")
            return cached
        
        # 执行查询
        start_time = time.time()
        result = await executor(sql, params) if asyncio.iscoroutinefunction(executor) else executor(sql, params)
        execution_time = time.time() - start_time
        
        # 记录统计
        self._record_stats(sql, execution_time)
        
        # 缓存结果
        self.cache.set(cache_key, result)
        
        return result
    
    def _record_stats(self, sql: str, execution_time: float) -> None:
        """记录查询统计"""
        # 简化SQL作为键
        simplified = sql.strip()[:100]
        
        if simplified not in self.query_stats:
            self.query_stats[simplified] = {
                "count": 0,
                "total_time": 0,
                "avg_time": 0,
                "max_time": 0
            }
        
        stats = self.query_stats[simplified]
        stats["count"] += 1
        stats["total_time"] += execution_time
        stats["avg_time"] = stats["total_time"] / stats["count"]
        stats["max_time"] = max(stats["max_time"], execution_time)
    
    def get_slow_queries(self, threshold_ms: float = 100) -> List[Dict]:
        """获取慢查询"""
        slow_queries = []
        
        for sql, stats in self.query_stats.items():
            avg_time_ms = stats["avg_time"] * 1000
            if avg_time_ms > threshold_ms:
                slow_queries.append({
                    "sql": sql,
                    "avg_time_ms": round(avg_time_ms, 2),
                    "max_time_ms": round(stats["max_time"] * 1000, 2),
                    "count": stats["count"]
                })
        
        return sorted(slow_queries, key=lambda x: x["avg_time_ms"], reverse=True)
    
    def suggest_indexes(self, slow_queries: List[Dict]) -> List[Dict]:
        """建议索引"""
        suggestions = []
        
        for query in slow_queries:
            sql = query["sql"].upper()
            
            # 分析WHERE子句
            if "WHERE" in sql:
                # 简单的启发式建议
                if "NAME" in sql and "NAMES" not in sql.upper():
                    suggestions.append({
                        "table": "names",
                        "column": "name",
                        "reason": f"查询频繁使用name字段过滤，平均耗时{query['avg_time_ms']}ms",
                        "priority": "high" if query["avg_time_ms"] > 500 else "medium"
                    })
                
                if "FILE_ID" in sql:
                    suggestions.append({
                        "table": "entities",
                        "column": "file_id",
                        "reason": f"查询频繁使用file_id关联，平均耗时{query['avg_time_ms']}ms",
                        "priority": "high"
                    })
        
        return suggestions
    
    def get_optimization_report(self) -> Dict[str, Any]:
        """获取优化报告"""
        cache_stats = self.cache.get_stats()
        slow_queries = self.get_slow_queries(threshold_ms=50)
        index_suggestions = self.suggest_indexes(slow_queries)
        
        return {
            "cache_stats": cache_stats,
            "slow_queries": slow_queries[:10],
            "index_suggestions": index_suggestions,
            "total_queries": sum(s["count"] for s in self.query_stats.values()),
            "unique_queries": len(self.query_stats)
        }
    
    def clear_cache(self) -> None:
        """清除缓存"""
        self.cache.clear()
    
    def preload_cache(
        self,
        executor: Callable,
        common_queries: List[str]
    ) -> None:
        """预加载缓存"""
        for sql in common_queries:
            try:
                result = executor(sql)
                cache_key = self._hash_query(sql)
                self.cache.set(cache_key, result)
            except Exception as e:
                logger.warning(f"预加载查询失败: {sql}, 错误: {e}")

