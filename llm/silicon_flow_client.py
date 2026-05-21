"""
Silicon Flow Client - 硅基流动API客户端
集成硅基流动Qwen2.5-7B模型，支持自然语言理解和SQL生成
"""

import json
import httpx
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from core.config_manager import get_configuration
from core.logger_manager import get_logger

logger = get_logger("silicon_flow_client")


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system, user, assistant
    content: str


@dataclass
class ChatCompletion:
    """聊天完成结果"""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str


class SiliconFlowClient:
    """硅基流动API客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0
    ):
        """
        初始化硅基流动客户端
        
        Args:
            api_key: API密钥，默认从配置读取
            model: 模型名称，默认从配置读取
            base_url: API基础URL，默认从配置读取
            timeout: 请求超时时间
        """
        config = get_configuration()
        
        self.api_key = api_key or config.silicon_flow_api_key
        self.model = model or config.silicon_flow_model
        self.base_url = base_url or config.silicon_flow_base_url
        self.timeout = timeout
        
        if not self.api_key:
            raise ValueError("API密钥不能为空，请设置SILICON_FLOW_API_KEY")
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=timeout
        )
        
        logger.info(f"初始化硅基流动客户端，模型: {self.model}")
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> ChatCompletion:
        """
        聊天完成
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            stream: 是否流式输出
            
        Returns:
            ChatCompletion: 完成结果
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        try:
            response = await self.client.post(
                "/chat/completions",
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("choices"):
                raise ValueError("API返回空结果（可能触发内容过滤）")
            choice = data["choices"][0]
            return ChatCompletion(
                content=choice["message"]["content"],
                model=data["model"],
                usage=data.get("usage", {}),
                finish_reason=choice.get("finish_reason", "")
            )
            
        except httpx.HTTPStatusError as e:
            logger.error(f"API请求失败: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            raise

    async def generate_sql(
        self,
        natural_language: str,
        schema_context: str,
        examples: Optional[List[Dict]] = None
    ) -> str:
        """
        生成SQL查询
        
        Args:
            natural_language: 自然语言查询
            schema_context: 数据库模式上下文
            examples: 示例查询列表
            
        Returns:
            str: 生成的SQL
        """
        system_prompt = self._build_sql_system_prompt(schema_context, examples)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请根据以下问题生成SQL查询：\n\n{natural_language}"}
        ]
        
        completion = await self.chat_completion(
            messages=messages,
            temperature=0.1,
            max_tokens=1000
        )
        
        return self._extract_sql(completion.content)

    def _build_sql_system_prompt(
        self,
        schema_context: str,
        examples: Optional[List[Dict]] = None
    ) -> str:
        """构建SQL系统提示"""
        prompt = f"""你是一个SQLite数据库专家。请将自然语言问题转换为有效的SQL查询。

数据库模式:
{schema_context}

重要规则:
1. 只生成SELECT查询，禁止任何修改数据的操作
2. 使用表别名提高可读性
3. 优先使用JOIN而不是子查询
4. 对文本搜索使用LIKE操作符
5. 限制结果数量（默认100条）
6. 返回的SQL必须可以直接执行

表关系说明:
- files: 存储文件信息
- entities: 存储代码实体（类、方法等）
- names: 存储实体名称（去重）
- entity_types: 实体类型枚举
- call_relations: 方法调用关系
- inheritance_relations: 继承关系
- component_relations: UI组件关系

请只返回SQL代码，不要包含任何解释或markdown格式。
"""
        
        if examples:
            prompt += "\n示例:\n"
            for i, example in enumerate(examples, 1):
                prompt += f"\n示例{i}:\n"
                prompt += f"问题: {example['question']}\n"
                prompt += f"SQL: {example['sql']}\n"
        
        return prompt
    
    def _extract_sql(self, content: str) -> str:
        """从响应中提取SQL"""
        # 尝试提取代码块
        if "```sql" in content:
            start = content.find("```sql") + 6
            end = content.find("```", start)
            if end == -1:
                end = len(content)
            return content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end == -1:
                end = len(content)
            return content[start:end].strip()
        
        # 清理内容
        sql = content.strip()
        
        # 移除可能的解释文字
        lines = sql.split('\n')
        sql_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('--') and not line.startswith('//'):
                sql_lines.append(line)
        
        return ' '.join(sql_lines)
    
    async def close(self) -> None:
        """关闭客户端"""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
