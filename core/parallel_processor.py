"""
Parallel Processor - 并行处理引擎
使用线程池实现并发处理（避免pickle序列化问题）

基于第一性原理：
- 用满所有CPU：多线程并行
- 不一次性加载：一个文件一个文件处理
- 流式处理：结果即时返回
"""

import os
import time
from typing import List, Dict, Callable, Any, Optional, TypeVar
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from dataclasses import dataclass

from core.logger_manager import get_logger
from core.progress_tracker import ProgressTracker

logger = get_logger("parallel_processor")

T = TypeVar('T')
R = TypeVar('R')


@dataclass
class ProcessingResult:
    """处理结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    processing_time: float = 0.0
    worker_id: int = 0


class ParallelProcessor:
    """并行处理器（线程池实现，避免pickle序列化问题）"""
    
    def __init__(
        self,
        max_workers: Optional[int] = None,
        chunk_size: int = 100,
        show_progress: bool = True
    ):
        self.max_workers = max_workers or min(cpu_count() or 4, 16)
        self.chunk_size = chunk_size
        self.show_progress = show_progress
        logger.info(f"初始化并行处理器: {self.max_workers} 个工作线程")
    
    def process_items(
        self,
        items: List[T],
        processor: Callable[[T], R],
        error_handler: Optional[Callable[[T, Exception], None]] = None
    ) -> List[ProcessingResult]:
        """并行处理项目列表（保持输入顺序）"""
        if not items:
            return []
        
        total_items = len(items)
        logger.info(f"开始并行处理 {total_items} 个项目")
        
        # 使用列表存储结果，保持顺序
        results: List[ProcessingResult] = [None] * total_items
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务，记录索引
            future_to_index = {
                executor.submit(self._wrap_processor, processor, item, i % self.max_workers): i
                for i, item in enumerate(items)
            }
            
            if self.show_progress:
                with ProgressTracker(f"Processing {total_items} items") as tracker:
                    tracker.set_total(total_items)
                    for future in as_completed(future_to_index):
                        index = future_to_index[future]
                        try:
                            result = future.result()
                            results[index] = result
                        except Exception as e:
                            logger.error(f"处理项目失败: {e}")
                            if error_handler:
                                error_handler(items[index], e)
                            results[index] = ProcessingResult(
                                success=False, data=None, error=str(e)
                            )
                        tracker.update()
            else:
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    try:
                        result = future.result()
                        results[index] = result
                    except Exception as e:
                        logger.error(f"处理项目失败: {e}")
                        if error_handler:
                            error_handler(items[index], e)
                        results[index] = ProcessingResult(
                            success=False, data=None, error=str(e)
                        )
        
        success_count = sum(1 for r in results if r and r.success)
        logger.info(f"处理完成: {success_count}/{total_items} 成功")
        return results
    
    def process_chunks(
        self,
        items: List[T],
        chunk_processor: Callable[[List[T]], List[R]],
        error_handler: Optional[Callable[[List[T], Exception], None]] = None
    ) -> List[ProcessingResult]:
        """分块并行处理"""
        if not items:
            return []
        
        chunks = self._split_into_chunks(items, self.chunk_size)
        total_chunks = len(chunks)
        logger.info(f"分块处理: {len(items)} 个项目分成 {total_chunks} 块")
        
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_chunk = {
                executor.submit(self._wrap_chunk_processor, chunk_processor, chunk, i % self.max_workers): chunk
                for i, chunk in enumerate(chunks)
            }
            
            if self.show_progress:
                with ProgressTracker(f"Processing {total_chunks} chunks") as tracker:
                    tracker.set_total(total_chunks)
                    for future in as_completed(future_to_chunk):
                        try:
                            result = future.result()
                            results.append(result)
                            tracker.update(advance=1)
                        except Exception as e:
                            logger.error(f"处理块失败: {e}")
                            results.append(ProcessingResult(
                                success=False, data=None, error=str(e)
                            ))
            else:
                for future in as_completed(future_to_chunk):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"处理块失败: {e}")
                        results.append(ProcessingResult(
                            success=False, data=None, error=str(e)
                        ))
        return results
    
    def _split_into_chunks(self, items: List[T], chunk_size: int) -> List[List[T]]:
        """将列表分块"""
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    
    def _wrap_processor(self, processor, item, worker_id):
        """包装单个处理器"""
        start_time = time.time()
        try:
            result = processor(item)
            return ProcessingResult(
                success=True, data=result,
                processing_time=time.time() - start_time, worker_id=worker_id
            )
        except Exception as e:
            return ProcessingResult(
                success=False, data=None, error=str(e),
                processing_time=time.time() - start_time, worker_id=worker_id
            )
    
    def _wrap_chunk_processor(self, chunk_processor, chunk, worker_id):
        """包装块处理器"""
        start_time = time.time()
        try:
            result = chunk_processor(chunk)
            return ProcessingResult(
                success=True, data=result,
                processing_time=time.time() - start_time, worker_id=worker_id
            )
        except Exception as e:
            return ProcessingResult(
                success=False, data=None, error=str(e),
                processing_time=time.time() - start_time, worker_id=worker_id
            )


class BatchInserter:
    """批量插入器"""
    
    def __init__(self, batch_size: int = 1000):
        self.batch_size = batch_size
        self.buffer: List[Any] = []
        self.total_inserted = 0
    
    def add(self, item: Any) -> Optional[List[Any]]:
        """添加项目到缓冲区，满则返回批次"""
        self.buffer.append(item)
        if len(self.buffer) >= self.batch_size:
            batch = self.buffer
            self.buffer = []
            self.total_inserted += len(batch)
            return batch
        return None
    
    def flush(self) -> Optional[List[Any]]:
        """刷新缓冲区"""
        if self.buffer:
            batch = self.buffer
            self.buffer = []
            self.total_inserted += len(batch)
            return batch
        return None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.flush()


def get_optimal_workers() -> int:
    """获取最优工作线程数"""
    cpu_cores = cpu_count() or 4
    return max(1, cpu_cores - 1)
