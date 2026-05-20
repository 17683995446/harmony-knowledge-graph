"""
AST Analyzer - AST分析器
基于抽象语法树的深度代码分析
"""

import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict

from core.logger_manager import get_logger
from parsers.arkts_parser import ParsedEntity, EntityType, ParseResult

logger = get_logger("ast_analyzer")


@dataclass
class DependencyGraph:
    """依赖关系图"""
    nodes: Dict[str, Dict] = field(default_factory=dict)
    edges: List[Dict] = field(default_factory=list)

    def add_node(self, node_id: str, node_type: str, data: Dict) -> None:
        """添加节点"""
        self.nodes[node_id] = {
            "type": node_type,
            "data": data
        }

    def add_edge(self, source: str, target: str, edge_type: str, data: Dict = None) -> None:
        """添加边"""
        self.edges.append({
            "source": source,
            "target": target,
            "type": edge_type,
            "data": data or {}
        })

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "nodes": self.nodes,
            "edges": self.edges
        }

    def to_cytoscape_format(self) -> List[Dict]:
        """转换为Cytoscape.js格式"""
        elements = []

        # 添加节点
        for node_id, node_data in self.nodes.items():
            elements.append({
                "data": {
                    "id": node_id,
                    **node_data["data"]
                }
            })

        # 添加边
        for i, edge in enumerate(self.edges):
            elements.append({
                "data": {
                    "id": f"e{i}",
                    "source": edge["source"],
                    "target": edge["target"],
                    "type": edge["type"],
                    **edge.get("data", {})
                }
            })

        return elements


@dataclass
class CodeMetrics:
    """代码度量指标"""
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0

    # 复杂度指标
    cyclomatic_complexity: int = 0
    cognitive_complexity: int = 0

    # 实体统计
    class_count: int = 0
    method_count: int = 0
    function_count: int = 0
    property_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "total_lines": self.total_lines,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "cognitive_complexity": self.cognitive_complexity,
            "class_count": self.class_count,
            "method_count": self.method_count,
            "function_count": self.function_count,
            "property_count": self.property_count
        }


class ASTAnalyzer:
    """AST分析器类"""

    def __init__(self):
        self.dependency_graph = DependencyGraph()
        self.metrics = CodeMetrics()
        self.entity_index: Dict[str, ParsedEntity] = {}
        self.file_entities: Dict[str, List[ParsedEntity]] = defaultdict(list)
        # 反向查找表：实体名称 -> 实体ID列表（用于从调用名称解析到实体ID）
        self._name_to_entity_ids: Dict[str, List[str]] = defaultdict(list)

    def analyze_results(self, parse_results: List[ParseResult]) -> Dict[str, Any]:
        """
        分析解析结果

        Args:
            parse_results: 解析结果列表

        Returns:
            分析结果字典
        """
        logger.info(f"开始分析 {len(parse_results)} 个文件的解析结果")

        # 建立实体索引
        self._build_entity_index(parse_results)

        # 构建依赖图
        self._build_dependency_graph(parse_results)

        # 计算代码度量
        self._calculate_metrics(parse_results)

        # 分析调用链
        call_chains = self._analyze_call_chains()

        # 分析组件层次
        component_hierarchy = self._analyze_component_hierarchy()

        return {
            "dependency_graph": self.dependency_graph.to_dict(),
            "cytoscape_elements": self.dependency_graph.to_cytoscape_format(),
            "metrics": self.metrics.to_dict(),
            "call_chains": call_chains,
            "component_hierarchy": component_hierarchy,
            "entity_count": len(self.entity_index),
            "file_count": len(parse_results)
        }

    def _build_entity_index(self, parse_results: List[ParseResult]) -> None:
        """建立实体索引"""
        for result in parse_results:
            for entity in result.entities:
                # 生成唯一ID
                entity_id = self._generate_entity_id(entity)
                self.entity_index[entity_id] = entity
                self.file_entities[result.file_path].append(entity)
                # 构建名称到实体ID的反向查找表
                self._name_to_entity_ids[entity.name].append(entity_id)

    def _generate_entity_id(self, entity: ParsedEntity) -> str:
        """生成实体唯一ID"""
        if entity.parent:
            return f"{entity.file_path}::{entity.parent}::{entity.name}"
        return f"{entity.file_path}::{entity.name}"

    def _resolve_call_to_entity_id(self, call: str) -> Optional[str]:
        """
        将调用名称字符串解析为实体ID。

        使用模糊匹配策略：
        - 如果调用是 "obj.method" 形式，提取 "method" 部分进行查找
        - 如果调用是 "method" 形式，直接用 "method" 查找
        - 返回第一个匹配的实体ID，如果找不到则返回 None
        """
        # 提取调用名称的最后一部分（处理 obj.method 形式）
        lookup_name = call.split(".")[-1] if "." in call else call

        # 在反向查找表中查找匹配的实体ID
        candidate_ids = self._name_to_entity_ids.get(lookup_name, [])

        if candidate_ids:
            # 优先返回同名精确匹配；如果有多个候选，返回第一个
            return candidate_ids[0]

        # 如果点分形式没匹配到，尝试完整调用名
        if "." in call:
            candidate_ids = self._name_to_entity_ids.get(call, [])
            if candidate_ids:
                return candidate_ids[0]

        return None

    def _build_dependency_graph(self, parse_results: List[ParseResult]) -> None:
        """构建依赖关系图"""
        # 添加文件节点
        for result in parse_results:
            file_id = f"file:{result.file_path}"
            self.dependency_graph.add_node(
                file_id,
                "file",
                {"path": result.file_path}
            )

            # 添加实体节点和文件-实体关系
            for entity in result.entities:
                entity_id = self._generate_entity_id(entity)
                self.dependency_graph.add_node(
                    entity_id,
                    entity.entity_type.value,
                    {
                        "name": entity.name,
                        "file": result.file_path,
                        "line": entity.location.line
                    }
                )

                # 文件包含实体
                self.dependency_graph.add_edge(
                    file_id,
                    entity_id,
                    "contains"
                )

                # 父子关系
                if entity.parent:
                    parent_id = f"{result.file_path}::{entity.parent}"
                    if parent_id in self.entity_index:
                        self.dependency_graph.add_edge(
                            parent_id,
                            entity_id,
                            "has_member"
                        )

                # 继承关系
                if entity.extends:
                    # 尝试找到父类
                    for other_result in parse_results:
                        for other_entity in other_result.entities:
                            if (other_entity.name == entity.extends and
                                other_entity.entity_type in (EntityType.CLASS, EntityType.INTERFACE)):
                                parent_id = self._generate_entity_id(other_entity)
                                self.dependency_graph.add_edge(
                                    entity_id,
                                    parent_id,
                                    "extends"
                                )

                # 调用关系 —— 尝试将调用名称解析为实体ID
                for call in entity.calls:
                    resolved_id = self._resolve_call_to_entity_id(call)
                    if resolved_id:
                        # 找到了对应的实体，使用实体ID作为目标
                        self.dependency_graph.add_edge(
                            entity_id,
                            resolved_id,
                            "calls",
                            {"call": call}
                        )
                    else:
                        # 未找到对应实体，创建一个未解析节点
                        unresolved_id = f"unresolved:{call}"
                        self.dependency_graph.add_node(
                            unresolved_id,
                            "unresolved",
                            {"name": call}
                        )
                        self.dependency_graph.add_edge(
                            entity_id,
                            unresolved_id,
                            "calls",
                            {"call": call}
                        )

            # 导入关系
            for imp in result.imports:
                source = imp.get("source", "")
                if source.startswith("."):
                    # 相对导入，建立文件间依赖
                    self.dependency_graph.add_edge(
                        file_id,
                        f"import:{source}",
                        "imports",
                        imp
                    )

    def _calculate_metrics(self, parse_results: List[ParseResult]) -> None:
        """计算代码度量指标"""
        for result in parse_results:
            try:
                with open(result.file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')

                    self.metrics.total_lines += len(lines)

                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            self.metrics.blank_lines += 1
                        elif stripped.startswith('//'):
                            self.metrics.comment_lines += 1
                        elif stripped.startswith('/*') or stripped.startswith('*'):
                            self.metrics.comment_lines += 1
                        else:
                            self.metrics.code_lines += 1
            except Exception as e:
                logger.warning(f"计算文件度量失败 {result.file_path}: {e}")

            # 统计实体
            for entity in result.entities:
                if entity.entity_type == EntityType.CLASS:
                    self.metrics.class_count += 1
                elif entity.entity_type == EntityType.METHOD:
                    self.metrics.method_count += 1
                elif entity.entity_type == EntityType.FUNCTION:
                    self.metrics.function_count += 1
                elif entity.entity_type == EntityType.PROPERTY:
                    self.metrics.property_count += 1

                # 简单复杂度估算
                if entity.entity_type in (EntityType.METHOD, EntityType.FUNCTION):
                    self.metrics.cyclomatic_complexity += 1

    def _analyze_call_chains(self) -> List[Dict]:
        """分析调用链"""
        chains = []

        # 找到入口方法（被调用但很少调用其他方法的）
        entry_points = self._find_entry_points()

        for entry in entry_points[:10]:  # 限制数量
            chain = self._trace_call_chain(entry, depth=0, max_depth=5)
            if chain:
                chains.append(chain)

        return chains

    def _find_entry_points(self) -> List[str]:
        """找到入口点"""
        entry_points = []

        for entity_id, entity in self.entity_index.items():
            if entity.entity_type == EntityType.METHOD:
                # 检查是否被装饰器标记（如@Entry, @Builder）
                if any(d in ("Entry", "Builder", "aboutToAppear", "onPageShow") for d in entity.annotations):
                    entry_points.append(entity_id)
                # 检查方法名是否是常见的生命周期方法
                elif entity.name in ("aboutToAppear", "onPageShow", "onPageHide", "onBackPress", "build"):
                    entry_points.append(entity_id)
            elif entity.entity_type == EntityType.FUNCTION:
                # 顶层函数也是入口点
                entry_points.append(entity_id)

        return entry_points

    def _trace_call_chain(
        self,
        entity_id: str,
        depth: int,
        max_depth: int,
        visited: Set[str] = None
    ) -> Optional[Dict]:
        """追踪调用链"""
        if visited is None:
            visited = set()

        if depth >= max_depth or entity_id in visited:
            return None

        visited.add(entity_id)

        entity = self.entity_index.get(entity_id)
        if not entity:
            return None

        chain = {
            "id": entity_id,
            "name": entity.name,
            "type": entity.entity_type.value,
            "file": entity.file_path,
            "line": entity.location.line,
            "calls": []
        }

        for call in entity.calls[:5]:  # 限制分支
            # 将调用名称解析为实体ID，而不是直接将名称字符串当作ID使用
            resolved_id = self._resolve_call_to_entity_id(call)
            if resolved_id:
                sub_chain = self._trace_call_chain(resolved_id, depth + 1, max_depth, visited.copy())
                if sub_chain:
                    chain["calls"].append(sub_chain)

        return chain

    def _analyze_component_hierarchy(self) -> List[Dict]:
        """分析组件层次结构"""
        hierarchy = []

        # 找到所有组件
        components = [
            e for e in self.entity_index.values()
            if e.entity_type == EntityType.COMPONENT
        ]

        for component in components:
            node = {
                "id": self._generate_entity_id(component),
                "name": component.name,
                "annotations": component.annotations,
                "file": component.file_path,
                "line": component.location.line,
                "children": []
            }
            hierarchy.append(node)

        return hierarchy

    def find_circular_dependencies(self) -> List[List[str]]:
        """查找循环依赖"""
        # 简化的循环检测
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: List[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            # 获取邻居
            neighbors = []
            for edge in self.dependency_graph.edges:
                if edge["source"] == node and edge["type"] in ("imports", "extends"):
                    neighbors.append(edge["target"])

            for neighbor in neighbors:
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # 发现循环
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for node in self.dependency_graph.nodes:
            if node not in visited:
                dfs(node, [])

        return cycles

    def get_entity_details(self, entity_id: str) -> Optional[Dict]:
        """获取实体详情"""
        entity = self.entity_index.get(entity_id)
        if not entity:
            return None

        # 找到相关实体
        related = []
        for edge in self.dependency_graph.edges:
            if edge["source"] == entity_id:
                related.append({
                    "type": edge["type"],
                    "target": edge["target"]
                })
            elif edge["target"] == entity_id:
                related.append({
                    "type": f"inverse_{edge['type']}",
                    "source": edge["source"]
                })

        return {
            "entity": entity.to_dict(),
            "relations": related
        }
