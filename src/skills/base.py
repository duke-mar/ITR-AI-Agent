"""
Skill 抽象基类

职责：
  - 定义所有 Skill 的公共接口
  - 提供基础工具方法（日志、配置读取等）

设计原则：
  - Skill 是无状态的，不持有业务上下文
  - Skill 可独立测试，不依赖 Node 或 Graph
"""

import logging
from abc import ABC
from typing import Any

logger = logging.getLogger(__name__)


class BaseSkill(ABC):
    """Skill 抽象基类"""

    def __init__(self, **kwargs):
        self._config = kwargs
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取初始化时传入的配置参数"""
        return self._config.get(key, default)

    def health_check(self) -> bool:
        """
        健康检查。
        子类可覆盖此方法，返回外部服务是否可用。
        """
        return True
