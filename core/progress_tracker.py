"""
Progress Tracker - 进度追踪器
实时显示处理进度，支持多阶段任务
"""

import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, TaskProgressColumn, TimeRemainingColumn
)
from rich.console import Console


@dataclass
class ProgressState:
    """进度状态数据类"""
    total: int = 0
    completed: int = 0
    current_stage: str = ""
    start_time: float = field(default_factory=time.time)
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    @property
    def percentage(self) -> float:
        """计算完成百分比"""
        if self.total == 0:
            if self.completed > 0:
                logging.warning(
                    f"ProgressState 状态不一致: total=0 但 completed={self.completed}，"
                    f"返回 100.0 表示已完成但无总量基准"
                )
                return 100.0
            return 0.0
        return (min(self.completed, self.total) / self.total) * 100
    
    @property
    def elapsed_time(self) -> float:
        """计算已用时间"""
        return time.time() - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total": self.total,
            "completed": self.completed,
            "percentage": round(self.percentage, 2),
            "current_stage": self.current_stage,
            "elapsed_time": round(self.elapsed_time, 2),
            "stages": self.stages
        }


class ProgressTracker:
    """进度追踪器类"""
    
    def __init__(self, description: str = "Processing"):
        self.description = description
        self.state = ProgressState()
        self._progress: Optional[Progress] = None
        self._task_id: Optional[int] = None
        self._console = Console()
    
    def __enter__(self):
        """上下文管理器入口"""
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=self._console
        )
        self._progress.start()
        self._task_id = self._progress.add_task(
            self.description,
            total=self.state.total
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self._progress:
            self._progress.stop()
    
    def set_total(self, total: int) -> None:
        """设置总任务数"""
        self.state.total = total
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, total=total)
    
    def update(self, advance: int = 1, description: Optional[str] = None) -> None:
        """更新进度"""
        self.state.completed += advance
        if self._progress and self._task_id is not None:
            kwargs = {"advance": advance}
            if description:
                kwargs["description"] = description
                self.state.current_stage = description
            self._progress.update(self._task_id, **kwargs)
    
    def set_stage(self, stage_name: str, stage_info: Optional[Dict[str, Any]] = None) -> None:
        """设置当前阶段"""
        self.state.current_stage = stage_name
        self.state.stages[stage_name] = {"start_time": time.time()}
        if stage_info:
            self.state.stages[stage_name].update(stage_info)
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=stage_name)
    
    def complete_stage(self, stage_name: str) -> None:
        """完成阶段"""
        if stage_name in self.state.stages:
            self.state.stages[stage_name]["end_time"] = time.time()
            self.state.stages[stage_name]["duration"] = (
                self.state.stages[stage_name]["end_time"] -
                self.state.stages[stage_name]["start_time"]
            )
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return self.state.to_dict()
    
    def print_summary(self) -> None:
        """打印进度摘要"""
        self._console.print(f"\n[bold green]✓[/bold green] {self.description}")
        self._console.print(f"  总计: {self.state.total}")
        self._console.print(f"  完成: {self.state.completed}")
        self._console.print(f"  耗时: {self.state.elapsed_time:.2f}秒")
