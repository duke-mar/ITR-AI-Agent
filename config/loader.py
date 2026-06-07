"""
业务配置加载器

职责：
  - 加载 config/intents/*.yaml 文件
  - 解析意图定义、字段结构、提取策略
  - 为 Node 提供配置化的业务数据

设计原则：
  - 所有业务数据外置到 YAML，代码只保留读取逻辑
  - 启动时一次性加载，运行时只读
"""

import logging
import os
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    raise ImportError("请安装 PyYAML: pip install pyyaml")

logger = logging.getLogger(__name__)


class OptionItem:
    """选项项"""
    def __init__(self, data: Dict[str, Any]):
        self.value = data.get("value", "")
        self.label = data.get("label", self.value)


class FieldConfig:
    """字段配置基类"""
    def __init__(self, field_id: str, label: str, required: bool = True):
        self.id = field_id
        self.label = label
        self.required = required


class OpenTextField(FieldConfig):
    """开放文本字段（第一轮由 LLM 提取）"""
    def __init__(self, data: Dict[str, Any]):
        super().__init__(
            data.get("id", ""),
            data.get("label", ""),
            data.get("required", False)
        )
        self.description = data.get("description", "")
        self.extraction_prompt = data.get("extraction_prompt", "")


class EnumField(FieldConfig):
    """枚举字段（前端显示选项卡片）"""
    def __init__(self, data: Dict[str, Any]):
        super().__init__(
            data.get("id", ""),
            data.get("label", ""),
            data.get("required", True)
        )
        self.options = [OptionItem(opt) for opt in data.get("options", [])]


class RuleField(FieldConfig):
    """规则字段（正则提取或 API 验证）"""
    def __init__(self, data: Dict[str, Any]):
        super().__init__(
            data.get("id", ""),
            data.get("label", ""),
            data.get("required", True)
        )
        self.field_type = data.get("type", "regex")  # regex / api
        self.pattern = data.get("pattern", "")
        self.example = data.get("example", "")
        self.error_message = data.get("error_message", "格式不正确，请重新输入")
        self.validation_api = data.get("validation", {})


class IntentConfig:
    """意图配置"""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id", "")
        self.name = data.get("name", self.id)
        self.description = data.get("description", "")

        # 三种字段类型
        self.open_text_fields: List[OpenTextField] = [
            OpenTextField(f) for f in data.get("open_text_fields", [])
        ]
        self.enum_fields: List[EnumField] = [
            EnumField(f) for f in data.get("enum_fields", [])
        ]
        self.rule_fields: List[RuleField] = [
            RuleField(f) for f in data.get("rule_fields", [])
        ]

        # 工作流配置
        self.workflow = data.get("workflow", {})

    def get_all_fields(self) -> List[FieldConfig]:
        """获取所有字段（按顺序：开放文本、枚举、规则）"""
        fields: List[FieldConfig] = []
        fields.extend(self.open_text_fields)
        fields.extend(self.enum_fields)
        fields.extend(self.rule_fields)
        return fields

    def get_all_field_ids(self) -> List[str]:
        """获取所有字段 ID"""
        return [f.id for f in self.get_all_fields()]

    def get_field(self, field_id: str) -> Optional[FieldConfig]:
        """按 ID 获取字段配置"""
        for f in self.get_all_fields():
            if f.id == field_id:
                return f
        return None

    def get_enum_field_options(self, field_id: str) -> List[OptionItem]:
        """获取枚举字段的选项列表"""
        for f in self.enum_fields:
            if f.id == field_id:
                return f.options
        return []

    def get_rule_field_config(self, field_id: str) -> Optional[RuleField]:
        """获取规则字段配置"""
        for f in self.rule_fields:
            if f.id == field_id:
                return f
        return None


class IntentRegistry:
    """
    意图注册表。

    加载 config/intents/*.yaml，提供统一的配置查询接口。
    """

    def __init__(self, config_dir: Optional[str] = None):
        self.intents: Dict[str, IntentConfig] = {}

        if config_dir is None:
            # 默认路径：项目根目录/config/intents
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_dir = os.path.join(project_root, "config", "intents")

        self.config_dir = config_dir
        self._load_all()

    def _load_all(self) -> None:
        """加载所有意图配置文件"""
        if not os.path.exists(self.config_dir):
            logger.warning(f"意图配置目录不存在: {self.config_dir}")
            return

        for filename in sorted(os.listdir(self.config_dir)):
            if not filename.endswith(".yaml"):
                continue

            filepath = os.path.join(self.config_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if data and "id" in data:
                    intent = IntentConfig(data)
                    self.intents[intent.id] = intent
                    logger.info(f"意图配置加载成功: {intent.id} ({intent.name})")
            except Exception as e:
                logger.error(f"加载意图配置失败 {filename}: {e}")

        logger.info(f"共加载 {len(self.intents)} 个意图配置")

    def get(self, intent_id: str) -> Optional[IntentConfig]:
        """按 ID 获取意图配置"""
        return self.intents.get(intent_id)

    def list_ids(self) -> List[str]:
        """列出所有意图 ID"""
        return list(self.intents.keys())

    def list_names(self) -> Dict[str, str]:
        """列出所有意图 ID 和名称"""
        return {k: v.name for k, v in self.intents.items()}

    def get_all_field_ids(self, intent_id: str) -> List[str]:
        """获取指定意图的所有字段 ID"""
        intent = self.get(intent_id)
        if intent:
            return intent.get_all_field_ids()
        return []

    def get_enum_options(self, intent_id: str, field_id: str) -> List[Dict[str, str]]:
        """获取枚举字段的选项（供前端渲染卡片）"""
        intent = self.get(intent_id)
        if not intent:
            return []
        options = intent.get_enum_field_options(field_id)
        return [{"value": opt.value, "label": opt.label} for opt in options]

    def get_rule_config(self, intent_id: str, field_id: str) -> Optional[Dict[str, Any]]:
        """获取规则字段配置"""
        intent = self.get(intent_id)
        if not intent:
            return None
        field = intent.get_rule_field_config(field_id)
        if field:
            return {
                "pattern": field.pattern,
                "example": field.example,
                "error_message": field.error_message,
            }
        return None
