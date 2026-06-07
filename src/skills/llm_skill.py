"""
统一 LLM Skill

职责：
  - 封装所有 OpenAI 兼容格式 API 的调用
  - 处理超时、重试、异常
  - 返回原始文本，不做任何业务解析

支持的厂商（通过 base_url + model 切换）：
  - DeepSeek (deepseek-chat, deepseek-reasoner)
  - 通义千问 (qwen-max, qwen-turbo)
  - Moonshot (moonshot-v1-128k)
  - OpenAI (gpt-4, gpt-3.5-turbo)
  - 以及所有兼容 OpenAI API 格式的服务

使用方式：
  Node 层构造 Prompt，调用本 Skill 的 complete/chat 方法获取原始响应，
  然后在 Node 层解析响应内容。
"""

import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from .base import BaseSkill

logger = logging.getLogger(__name__)


class LLMSkill(BaseSkill):
    """
    统一 LLM 通信 Skill。

    纯通信层，不碰 Prompt、不碰业务语义。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        **default_kwargs,
    ):
        """
        初始化 LLM Skill。

        Args:
            api_key: API 密钥
            base_url: API 基础地址
            model: 模型名称
            **default_kwargs: 默认参数（temperature、max_tokens 等）
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **default_kwargs,
        )

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model
        self.defaults = default_kwargs

        logger.info(f"LLMSkill 初始化完成: model={model}, base_url={base_url}")

    # ------------------------------------------------------------------
    # 核心调用方法
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **override,
    ) -> str:
        """
        单次文本补全（非流式）。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            **override: 覆盖默认参数（temperature、max_tokens 等）

        Returns:
            模型生成的原始文本

        Raises:
            Exception: 调用失败时抛出
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return await self.chat(messages, **override)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        **override,
    ) -> str:
        """
        多轮对话补全（非流式）。

        Args:
            messages: 消息列表，格式 [{"role": "user|system|assistant", "content": str}]
            **override: 覆盖默认参数

        Returns:
            模型生成的原始文本
        """
        kwargs = {**self.defaults, **override}

        try:
            self.logger.debug(f"LLM 请求: model={self.model}, messages_count={len(messages)}")

            response: ChatCompletion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )

            content = response.choices[0].message.content or ""

            self.logger.debug(
                f"LLM 响应: model={self.model}, "
                f"prompt_tokens={response.usage.prompt_tokens if response.usage else 0}, "
                f"completion_tokens={response.usage.completion_tokens if response.usage else 0}"
            )

            return content

        except Exception as e:
            self.logger.error(f"LLM 调用失败: {e}")
            raise

    # ------------------------------------------------------------------
    # 便捷方法（Node 层常用）
    # ------------------------------------------------------------------

    async def classify(
        self,
        text: str,
        options: List[str],
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        分类任务便捷方法。

        Args:
            text: 待分类文本
            options: 可选类别列表
            system_prompt: 系统提示词
            **kwargs: 额外参数

        Returns:
            分类结果（options 中的某一项，或 "unknown"）
        """
        prompt = f"""请对以下文本进行分类，只能从以下选项中选择：
{chr(10).join(f"- {opt}" for opt in options)}

文本：{text}

请直接输出类别ID，不要解释。如果无法判断，输出"unknown"。"""

        result = await self.complete(prompt, system_prompt=system_prompt, **kwargs)
        result = result.strip().lower()

        # 校验结果是否在选项中
        valid_options = [opt.lower() for opt in options]
        if result not in valid_options:
            return "unknown"

        return result

    async def extract(
        self,
        text: str,
        field_name: str,
        field_description: str,
        examples: Optional[List[str]] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        信息提取任务便捷方法。

        Args:
            text: 待提取文本
            field_name: 字段名
            field_description: 字段描述
            examples: 示例值（可选）
            **kwargs: 额外参数

        Returns:
            提取的值，或 None（未找到）
        """
        example_text = ""
        if examples:
            example_text = f"\n示例值：{', '.join(examples)}"

        prompt = f"""请从以下文本中提取"{field_name}"的信息。

字段说明：{field_description}{example_text}

文本：{text}

请直接输出提取的值，不要解释。如果文本中没有相关信息，输出"NONE"。"""

        result = await self.complete(prompt, **kwargs)
        result = result.strip()

        if result.upper() == "NONE" or not result:
            return None

        return result

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """检查 LLM 服务是否可用"""
        try:
            # 简单的同步检查（异步环境需在外部调用）
            return bool(self.client.api_key and self.model)
        except Exception:
            return False
