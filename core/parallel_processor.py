"""
Parallel Processor - 并行处理引擎
使用线程池实现并发处理（避免pickle序列化问题）

基于第一性原理：
- 用满所有CPU：多线程并行
- 不一次性加载：一个文件一个文件处理
- 流式处理：结果即时返回
"""

import time
from typing import List, Callable, Any, Optional, TypeVar
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

    def shutdown(self) -> None:
        """关闭并行处理器，释放资源"""
        logger.debug("ParallelProcessor shutdown")
        # 当前实现使用ThreadPoolExecutor作为上下文管理器
        # 资源在process_items方法结束时自动释放
        # 此方法用于未来扩展和API一致性

