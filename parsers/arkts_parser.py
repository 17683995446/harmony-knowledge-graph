"""
ArkTS Parser - ArkTS代码解析器
解析ArkTS/TypeScript代码，提取类、方法、变量等实体
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Set, Any, Tuple
from enum import Enum, auto

from core.logger_manager import get_logger

logger = get_logger("arkts_parser")


class EntityType(Enum):
    """实体类型枚举"""
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    METHOD = "method"
    FUNCTION = "function"
    PROPERTY = "property"
    VARIABLE = "variable"
    IMPORT = "import"
    EXPORT = "export"
    DECORATOR = "decorator"
    COMPONENT = "component"  # ArkUI组件


@dataclass
class SourceLocation:
    """源代码位置"""
    line: int
    column: int
    end_line: int = 0
    end_column: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ParsedEntity:
    """解析后的实体"""
    name: str
    entity_type: EntityType
    file_path: str
    location: SourceLocation
    parent: Optional[str] = None
    modifiers: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    parameters: List[Dict] = field(default_factory=list)
    return_type: Optional[str] = None
    extends: Optional[str] = None
    implements: List[str] = field(default_factory=list)
    body: Optional[str] = None
    documentation: Optional[str] = None

    # 关系
    calls: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "name": self.name,
            "entity_type": self.entity_type.value,
            "file_path": self.file_path,
            "location": self.location.to_dict(),
            "parent": self.parent,
            "modifiers": self.modifiers,
            "annotations": self.annotations,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "extends": self.extends,
            "implements": self.implements,
            "documentation": self.documentation,
            "calls": self.calls,
            "references": self.references
        }


@dataclass
class ParseResult:
    """解析结果"""
    file_path: str
    entities: List[ParsedEntity] = field(default_factory=list)
    imports: List[Dict] = field(default_factory=list)
    exports: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "entities": [e.to_dict() for e in self.entities],
            "imports": self.imports,
            "exports": self.exports,
            "errors": self.errors
        }


class ArkTSParser:
    """ArkTS代码解析器"""

    # ArkTS装饰器模式
    DECORATOR_PATTERN = re.compile(r'@(\w+)(?:\([^)]*\))?')

    # 类/接口/枚举定义模式
    CLASS_PATTERN = re.compile(
        r'(?:export\s+)?(?:abstract\s+)?(class|interface|enum)\s+(\w+)'
        r'(?:\s+extends\s+(\w+))?'
        r'(?:\s+implements\s+([\w\s,]+))?'
        r'\s*\{',
        re.MULTILINE
    )

    # 方法/函数定义模式
    METHOD_PATTERN = re.compile(
        r'(?:async\s+)?(?:static\s+)?(?:private\s+)?(?:protected\s+)?(?:public\s+)?'
        r'(?:override\s+)?'
        r'(\w+)\s*\(([^)]*)\)'
        r'(?:\s*:\s*([\w<>\[\]|\s]+))?'
        r'\s*(?:\{|=>)',
        re.MULTILINE
    )

    # 属性定义模式
    PROPERTY_PATTERN = re.compile(
        r'(?:readonly\s+)?(?:static\s+)?(?:private\s+)?(?:protected\s+)?(?:public\s+)?'
        r'(\w+)\s*:\s*([\w<>\[\]|\s]+)'
        r'(?:\s*=\s*([^;]+))?;',
        re.MULTILINE
    )

    # 导入语句模式
    IMPORT_PATTERN = re.compile(
        r'import\s+(?:(\{[^}]+\})|(\w+)|\*\s+as\s+(\w+))\s+from\s+[\'"]([^\'"]+)[\'"]',
        re.MULTILINE
    )

    # 导出语句模式
    EXPORT_PATTERN = re.compile(
        r'export\s+(?:default\s+)?(?:class|interface|enum|function|const|let|var)?\s*(\w+)?',
        re.MULTILINE
    )

    # ArkUI组件模式 (@Component, @Entry等)
    ARKUI_COMPONENT_PATTERN = re.compile(
        r'@(?:Component|Entry|Preview|CustomDialog)\s+(?:export\s+)?class\s+(\w+)',
        re.MULTILINE
    )

    # 函数调用模式
    CALL_PATTERN = re.compile(
        r'(?:(\w+)\.)?(\w+)\s*\([^)]*\)',
        re.MULTILINE
    )

    # 需要过滤的语言关键字（不是真正的函数调用）
    LANGUAGE_KEYWORDS: Set[str] = {
        'if', 'while', 'for', 'switch', 'catch', 'new', 'return', 'throw',
        'typeof', 'instanceof', 'else', 'do', 'try', 'finally', 'case',
        'break', 'continue', 'class', 'interface', 'enum', 'type', 'import',
        'export', 'from', 'as', 'extends', 'implements', 'super', 'this',
        'void', 'delete', 'in', 'of', 'yield', 'await', 'async', 'static',
        'get', 'set', 'readonly', 'abstract', 'override', 'public', 'private',
        'protected', 'const', 'let', 'var', 'function', 'true', 'false', 'null',
        'undefined', 'NaN', 'Infinity',
    }

    # 常见类型名（通常不是函数调用）
    COMMON_TYPE_NAMES: Set[str] = {
        'string', 'number', 'boolean', 'object', 'any', 'unknown', 'never',
        'void', 'undefined', 'null', 'Array', 'Map', 'Set', 'Promise',
        'Record', 'Partial', 'Required', 'Readonly', 'Pick', 'Omit',
        'Exclude', 'Extract', 'NonNullable', 'ReturnType', 'InstanceType',
        'Parameters', 'ConstructorParameters', 'String', 'Number', 'Boolean',
        'Object', 'Symbol', 'BigInt', 'Function', 'Error', 'RegExp', 'Date',
        'Int8Array', 'Uint8Array', 'Uint8ClampedArray', 'Int16Array',
        'Uint16Array', 'Int32Array', 'Uint32Array', 'Float32Array', 'Float64Array',
        'ArrayBuffer', 'SharedArrayBuffer', 'DataView', 'Iterator', 'Iterable',
        'MapIterator', 'SetIterator', 'Generator', 'AsyncIterator',
        'AsyncIterable', 'AsyncGenerator', 'ArrayLike', 'IterableIterator',
    }

    def __init__(self):
        self.current_file: Optional[str] = None
        self.current_content: Optional[str] = None
        self.line_offsets: List[int] = []

    def parse_file(self, file_path: str) -> ParseResult:
        """
        解析单个ArkTS文件

        Args:
            file_path: 文件路径

        Returns:
            ParseResult: 解析结果
        """
        self.current_file = file_path
        result = ParseResult(file_path=file_path)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.current_content = f.read()

            self._build_line_offsets()

            # 解析各种实体
            result.entities.extend(self._parse_classes())
            result.entities.extend(self._parse_methods())
            result.entities.extend(self._parse_properties())
            result.entities.extend(self._parse_arkui_components())

            # 解析导入导出
            result.imports = self._parse_imports()
            result.exports = self._parse_exports()

            # 解析调用关系
            self._parse_call_relations(result.entities)

            logger.debug(f"解析文件成功: {file_path}, 发现 {len(result.entities)} 个实体")

        except Exception as e:
            error_msg = f"解析文件失败 {file_path}: {str(e)}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        return result

    def _build_line_offsets(self) -> None:
        """构建行偏移表"""
        self.line_offsets = [0]
        for i, char in enumerate(self.current_content):
            if char == '\n':
                self.line_offsets.append(i + 1)

    def _get_location(self, pos: int) -> SourceLocation:
        """获取指定位置的源代码位置"""
        line = 1
        for i, offset in enumerate(self.line_offsets):
            if offset > pos:
                line = i
                break
            line = i + 1

        column = pos - self.line_offsets[line - 1] + 1
        return SourceLocation(line=line, column=column)

    def _parse_classes(self) -> List[ParsedEntity]:
        """解析类定义"""
        entities = []

        for match in self.CLASS_PATTERN.finditer(self.current_content):
            type_name = match.group(1)
            class_name = match.group(2)
            extends = match.group(3)
            implements_str = match.group(4)

            location = self._get_location(match.start())
            end_location = self._get_location(match.end())
            location.end_line = end_location.line
            location.end_column = end_location.column

            entity_type = EntityType.CLASS
            if type_name == "interface":
                entity_type = EntityType.INTERFACE
            elif type_name == "enum":
                entity_type = EntityType.ENUM

            implements = []
            if implements_str:
                implements = [i.strip() for i in implements_str.split(',')]

            entity = ParsedEntity(
                name=class_name,
                entity_type=entity_type,
                file_path=self.current_file,
                location=location,
                extends=extends,
                implements=implements
            )

            entities.append(entity)

        return entities

    def _parse_methods(self) -> List[ParsedEntity]:
        """解析方法定义"""
        entities = []

        for match in self.METHOD_PATTERN.finditer(self.current_content):
            method_name = match.group(1)
            params_str = match.group(2)
            return_type = match.group(3)

            # 跳过关键字
            if method_name in ('if', 'while', 'for', 'switch', 'catch'):
                continue

            location = self._get_location(match.start())
            end_location = self._get_location(match.end())
            location.end_line = end_location.line
            location.end_column = end_location.column

            # 解析参数
            parameters = self._parse_parameters(params_str)

            entity = ParsedEntity(
                name=method_name,
                entity_type=EntityType.METHOD,
                file_path=self.current_file,
                location=location,
                parameters=parameters,
                return_type=return_type.strip() if return_type else None
            )

            entities.append(entity)

        return entities

    def _parse_parameters(self, params_str: str) -> List[Dict]:
        """解析参数列表"""
        parameters = []
        if not params_str.strip():
            return parameters

        # 简单解析，处理基本参数
        for param in params_str.split(','):
            param = param.strip()
            if not param:
                continue

            parts = param.split(':')
            param_name = parts[0].strip()
            param_type = parts[1].strip() if len(parts) > 1 else 'any'

            parameters.append({
                "name": param_name,
                "type": param_type
            })

        return parameters

    def _parse_properties(self) -> List[ParsedEntity]:
        """解析属性定义"""
        entities = []

        for match in self.PROPERTY_PATTERN.finditer(self.current_content):
            prop_name = match.group(1)
            prop_type = match.group(2)
            default_value = match.group(3)

            location = self._get_location(match.start())
            end_location = self._get_location(match.end())
            location.end_line = end_location.line
            location.end_column = end_location.column

            entity = ParsedEntity(
                name=prop_name,
                entity_type=EntityType.PROPERTY,
                file_path=self.current_file,
                location=location,
                return_type=prop_type.strip()
            )

            entities.append(entity)

        return entities

    def _parse_arkui_components(self) -> List[ParsedEntity]:
        """解析ArkUI组件"""
        entities = []

        for match in self.ARKUI_COMPONENT_PATTERN.finditer(self.current_content):
            class_name = match.group(1)

            location = self._get_location(match.start())
            end_location = self._get_location(match.end())
            location.end_line = end_location.line
            location.end_column = end_location.column

            # 提取装饰器
            decorators = []
            for dec_match in self.DECORATOR_PATTERN.finditer(
                self.current_content[max(0, match.start() - 200):match.start()]
            ):
                decorators.append(dec_match.group(1))

            entity = ParsedEntity(
                name=class_name,
                entity_type=EntityType.COMPONENT,
                file_path=self.current_file,
                location=location,
                annotations=decorators
            )

            entities.append(entity)

        return entities

    def _parse_imports(self) -> List[Dict]:
        """解析导入语句"""
        imports = []

        for match in self.IMPORT_PATTERN.finditer(self.current_content):
            named_imports = match.group(1)
            default_import = match.group(2)
            namespace_import = match.group(3)
            source = match.group(4)

            import_info = {
                "source": source,
                "named": [],
                "default": default_import,
                "namespace": namespace_import
            }

            if named_imports:
                # 解析 { A, B as C }
                named = named_imports.strip('{}').split(',')
                import_info["named"] = [n.strip() for n in named if n.strip()]

            imports.append(import_info)

        return imports

    def _parse_exports(self) -> List[Dict]:
        """解析导出语句"""
        exports = []

        for match in self.EXPORT_PATTERN.finditer(self.current_content):
            export_name = match.group(1)
            is_default = 'default' in match.group(0)

            exports.append({
                "name": export_name,
                "is_default": is_default
            })

        return exports

    def _find_method_body_range(self, entity: ParsedEntity) -> Optional[Tuple[int, int]]:
        """
        通过花括号匹配找到方法体的范围 [start, end)
        优化版本：使用简单启发式方法，避免复杂扫描
        """
        if not self.current_content:
            return None

        content = self.current_content
        content_len = len(content)

        # 从实体的源码位置开始搜索
        line_index = entity.location.line - 1
        if line_index >= len(self.line_offsets):
            return None

        search_start = self.line_offsets[line_index]
        
        # 快速查找：从方法行开始向后查找第一个 '{'
        # 限制搜索范围到方法行后500字符，避免扫描整个文件
        search_limit = min(search_start + 500, content_len)
        brace_pos = content.find('{', search_start, search_limit)
        
        if brace_pos == -1:
            # 可能是箭头函数表达式
            arrow_pos = content.find('=>', search_start, search_limit)
            if arrow_pos != -1:
                j = arrow_pos + 2
                while j < content_len and content[j] in ' \t\n\r':
                    j += 1
                if j < content_len and content[j] == '{':
                    brace_pos = j
                else:
                    # 表达式体，到分号或行尾
                    expr_end = j
                    while expr_end < content_len and content[expr_end] not in ';\n':
                        expr_end += 1
                    return (j, expr_end)
            return None

        # 简化的花括号匹配 - 限制扫描范围
        body_start = brace_pos + 1
        depth = 1
        pos = brace_pos + 1
        max_scan = min(pos + 10000, content_len)  # 限制最大扫描10KB

        while pos < max_scan and depth > 0:
            ch = content[pos]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            pos += 1

        if depth == 0:
            return (body_start, pos - 1)

        return None

    def _is_inside_string_literal(self, pos: int) -> bool:
        """
        判断给定位置是否在字符串字面量内。

        通过从文件开头扫描到目标位置，追踪引号状态来判断。
        会正确处理转义字符和模板字符串。

        Args:
            pos: 文件内容中的字符位置

        Returns:
            True 如果该位置在字符串字面量内
        """
        if not self.current_content or pos < 0 or pos >= len(self.current_content):
            return False

        content = self.current_content
        content_len = len(content)
        i = 0
        while i < pos:
            ch = content[i]
            if ch == '/' and i + 1 < content_len:
                # 跳过单行注释
                if content[i + 1] == '/':
                    while i < pos and content[i] != '\n':
                        i += 1
                    continue
                # 跳过多行注释
                if content[i + 1] == '*':
                    i += 2
                    while i < pos and not (content[i] == '*' and content[i + 1] == '/'):
                        i += 1
                    i += 2
                    continue
            if ch == '"' or ch == "'" or ch == '`':
                quote = ch
                i += 1
                while i < pos and content[i] != quote:
                    if content[i] == '\\':
                        i += 1  # 跳过转义字符
                    i += 1
                if i < pos and content[i] == quote:
                    i += 1
                    # 如果 pos 恰好在引号之后，不在字符串内
                    if i >= pos:
                        return False
                else:
                    # 没有找到闭合引号，pos 在未闭合的字符串内
                    return True
                continue
            i += 1
        return False

    def _is_inside_comment(self, pos: int) -> bool:
        """
        判断给定位置是否在注释内。

        Args:
            pos: 文件内容中的字符位置

        Returns:
            True 如果该位置在注释内
        """
        if not self.current_content or pos < 0 or pos >= len(self.current_content):
            return False

        content = self.current_content
        i = 0
        while i < pos:
            ch = content[i]
            if ch == '/' and i + 1 < len(content):
                if content[i + 1] == '/':
                    # 单行注释，到行尾
                    while i < pos and content[i] != '\n':
                        i += 1
                    if i < pos:
                        return True
                    return False
                if content[i + 1] == '*':
                    # 多行注释
                    i += 2
                    while i < pos and not (content[i] == '*' and i + 1 < len(content) and content[i + 1] == '/'):
                        i += 1
                    if i < pos:
                        # 找到了注释结束
                        i += 2
                        continue
                    else:
                        # pos 在未闭合的多行注释内
                        return True
            if ch == '"' or ch == "'" or ch == '`':
                # 跳过字符串
                quote = ch
                i += 1
                while i < len(content) and content[i] != quote:
                    if content[i] == '\\':
                        i += 1
                    i += 1
                i += 1
                continue
            i += 1
        return False

    def _extract_calls_from_content(self, start: int = 0, end: Optional[int] = None,
                                     entity_name: Optional[str] = None) -> List[str]:
        """
        从指定范围的内容中提取函数调用（优化版本）。
        跳过昂贵的字符串/注释检查，使用简单启发式方法。
        """
        calls = []

        if not self.current_content:
            return calls

        content = self.current_content

        if end is None:
            end = len(content)

        # 限制搜索范围
        search_region = content[start:end]

        for match in self.CALL_PATTERN.finditer(search_region):
            obj = match.group(1)
            method = match.group(2)

            # 快速过滤语言关键字
            if method in self.LANGUAGE_KEYWORDS:
                continue

            # 过滤常见类型名
            if obj is None and method in self.COMMON_TYPE_NAMES:
                continue

            if obj:
                call_name = f"{obj}.{method}"
            else:
                call_name = method

            # 标记自递归调用
            if entity_name and call_name == entity_name:
                call_name = f"{call_name}(self)"

            calls.append(call_name)

        return list(set(calls))  # 去重

    def _parse_call_relations(self, entities: List[ParsedEntity]) -> None:
        """
        解析调用关系。

        对每个 METHOD/FUNCTION 实体，通过花括号匹配定位其方法体范围，
        然后仅在该范围内提取函数调用，避免将整个文件的调用分配给每个方法。

        Args:
            entities: 解析后的实体列表
        """
        for entity in entities:
            if entity.entity_type in (EntityType.METHOD, EntityType.FUNCTION):
                # 通过花括号匹配找到方法体范围
                body_range = self._find_method_body_range(entity)

                if body_range is not None:
                    body_start, body_end = body_range
                    entity.calls = self._extract_calls_from_content(
                        start=body_start,
                        end=body_end,
                        entity_name=entity.name
                    )
                else:
                    # 无法定位方法体，记录警告并留空
                    logger.debug(
                        f"无法定位方法体范围: {entity.name} "
                        f"(文件: {self.current_file}, 行: {entity.location.line})"
                    )
                    entity.calls = []

    def parse_batch(self, file_paths: List[str]) -> List[ParseResult]:
        """批量解析文件"""
        results = []

        for file_path in file_paths:
            result = self.parse_file(file_path)
            results.append(result)

        return results
