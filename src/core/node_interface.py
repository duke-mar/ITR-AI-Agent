"""
Node 抽象接口

所有业务 Node 必须实现此接口。
Node 的职责：接收 State → 执行业务逻辑 → 返回 State 更新片段。
Node 禁止：碰路由逻辑、碰 WebSocket、直接操作数据库。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type

from .state import ITRState


class INode(ABC):
    """Node 抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Node 唯一标识名，用于 Graph 注册和路由"""
        ...

    @abstractmethod
    async def execute(self, state: ITRState) -> Dict[str, Any]:
        """
        执行业务逻辑。

        Args:
            state: 当前全局 State 的快照

        Returns:
            State 更新片段，LangGraph 会自动合并到全局 State
            例如: {"intent": "technical", "messages": [...]}
        """
        ...

    def required_skills(self) -> List[Type]:
        """
        声明本 Node 依赖的 Skill 类型列表。
        GraphBuilder 启动时会做依赖校验。
        """
        return []
