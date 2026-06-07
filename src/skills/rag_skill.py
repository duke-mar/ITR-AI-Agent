"""
RAG Skill（知识库检索）

职责：
  - 封装知识库/向量数据库的检索调用
  - 支持多种 RAG 后端（Dify、RAGFlow、自研等）

当前状态：
  - 接口已定义，具体实现待接入
  - 需要用户在 .env 中配置 RAG_BASE_URL 和 RAG_API_KEY
"""

import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from .base import BaseSkill

logger = logging.getLogger(__name__)


@dataclass
class RAGSearchResult:
    """RAG 检索结果"""
    content: str
    source: str
    score: float
    metadata: Optional[dict] = None


class RAGSkill(BaseSkill):
    """
    RAG 检索 Skill 抽象基类。

    具体实现子类：
      - DifyRAGSkill: 对接 Dify 平台
      - RAGFlowSkill: 对接 RAGFlow 平台
      - CustomRAGSkill: 对接自研 RAG 服务
    """

    def __init__(self, base_url: str, api_key: str = "", top_k: int = 3, **kwargs):
        super().__init__(base_url=base_url, api_key=api_key, top_k=top_k, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.top_k = top_k

    @abstractmethod
    async def search(self, query: str, top_k: Optional[int] = None) -> List[RAGSearchResult]:
        """
        检索知识库。

        Args:
            query: 查询语句
            top_k: 返回结果数量（覆盖默认配置）

        Returns:
            检索结果列表，按相关性排序
        """
        ...

    async def search_and_format(
        self,
        query: str,
        top_k: Optional[int] = None,
        max_length: int = 2000,
    ) -> str:
        """
        检索并格式化为文本（供 Node 层直接使用）。

        Args:
            query: 查询语句
            top_k: 返回结果数量
            max_length: 最大总长度

        Returns:
            格式化后的检索结果文本
        """
        results = await self.search(query, top_k)
        if not results:
            return "未检索到相关知识。"

        parts = []
        total_len = 0
        for i, r in enumerate(results, 1):
            part = f"[知识{i}] 来源：{r.source}\n{r.content}\n"
            if total_len + len(part) > max_length:
                break
            parts.append(part)
            total_len += len(part)

        return "\n".join(parts)


# ===================================================================
# 预留实现类（用户按需接入）
# ===================================================================

class DifyRAGSkill(RAGSkill):
    """
    Dify 平台 RAG 对接实现。

    需要配置：
      RAG_BASE_URL=https://your-dify-app.com/v1
      RAG_API_KEY=your-dify-api-key
    """

    async def search(self, query: str, top_k: Optional[int] = None) -> List[RAGSearchResult]:
        """TODO: 实现 Dify API 调用"""
        logger.warning("DifyRAGSkill.search() 尚未实现，请接入 Dify API")
        # 示例实现框架：
        # async with aiohttp.ClientSession() as session:
        #     headers = {"Authorization": f"Bearer {self.api_key}"}
        #     payload = {"query": query, "retrieval_mode": "semantic"}
        #     async with session.post(f"{self.base_url}/chat-messages", ...) as resp:
        #         data = await resp.json()
        #         ...
        return []


class RAGFlowSkill(RAGSkill):
    """
    RAGFlow 平台对接实现。

    需要配置：
      RAG_BASE_URL=https://your-ragflow.com/api
      RAG_API_KEY=your-ragflow-api-key
    """

    async def search(self, query: str, top_k: Optional[int] = None) -> List[RAGSearchResult]:
        """TODO: 实现 RAGFlow API 调用"""
        logger.warning("RAGFlowSkill.search() 尚未实现，请接入 RAGFlow API")
        return []
