"""
Skill 注册与依赖注入

职责：
  - 统一管理所有 Skill 实例的生命周期
  - 为 Node 提供依赖注入支持
  - 启动时校验 Node 声明的 Skill 依赖是否满足
"""

import logging
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表，单例模式"""

    def __init__(self):
        self._skills: Dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        """注册一个 Skill 实例"""
        if name in self._skills:
            logger.warning(f"Skill '{name}' 已被注册，将被覆盖")
        self._skills[name] = instance
        logger.info(f"Skill 注册成功: {name} -> {type(instance).__name__}")

    def get(self, name: str) -> Optional[Any]:
        """按名称获取 Skill 实例"""
        return self._skills.get(name)

    def get_by_type(self, skill_type: Type) -> Optional[Any]:
        """按类型获取 Skill 实例（返回第一个匹配的）"""
        for instance in self._skills.values():
            if isinstance(instance, skill_type):
                return instance
        return None

    def has(self, name: str) -> bool:
        """判断 Skill 是否已注册"""
        return name in self._skills

    def list_skills(self) -> List[str]:
        """列出所有已注册的 Skill 名称"""
        return list(self._skills.keys())

    def validate_node_dependencies(self, node) -> List[str]:
        """
        校验 Node 声明的 Skill 依赖是否已满足。
        返回缺失的 Skill 类型名列表（空列表表示全部满足）。
        """
        from .node_interface import INode

        if not isinstance(node, INode):
            return []

        missing = []
        for skill_type in node.required_skills():
            found = self.get_by_type(skill_type)
            if found is None:
                missing.append(skill_type.__name__)

        return missing


# 全局单例
skill_registry = SkillRegistry()
