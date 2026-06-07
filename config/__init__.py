"""
配置层

设计原则：
  - 敏感信息（API Key、密码）→ 环境变量（.env）
  - 运行期参数（URL、模型名、开关）→ Pydantic Settings 读取环境变量
  - 业务配置（意图定义、字段结构）→ YAML 文件，产品/运营可直接编辑
"""

from .settings import settings, Settings
from .loader import IntentRegistry, IntentConfig, FieldConfig

__all__ = ["settings", "Settings", "IntentRegistry", "IntentConfig", "FieldConfig"]
