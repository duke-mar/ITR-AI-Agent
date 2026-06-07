"""
方案生成 Node（简化版）

职责：
  - 根据识别出的意图，直接生成回复（不经过信息收集）
  - 调用 LLM 生成针对性的解决方案
  - 如果置信度低或无法解决，提供转人工选项

设计原则：
  - 不依赖 collected_info（追问逻辑已移除）
  - 直接根据意图和对话历史生成回复
  - 所有 Prompt 和业务逻辑在 Node 层实现
"""

import logging
from typing import Any, Dict, List, Optional

from core.node_interface import INode
from core.state import ITRState
from skills.llm_skill import LLMSkill
from skills.rag_skill import RAGSkill

logger = logging.getLogger(__name__)


class SolutionGenerationNode(INode):
    """方案生成 Node —— 简化版，直接回复"""

    name = "solution_generation"

    def __init__(
        self,
        llm: LLMSkill,
        rag: Optional[RAGSkill] = None,
    ):
        self.llm = llm
        self.rag = rag

    def required_skills(self):
        skills = [LLMSkill]
        if self.rag:
            skills.append(RAGSkill)
        return skills

    async def execute(self, state: ITRState) -> Dict[str, Any]:
        """执行方案生成"""
        logger.info("=" * 50)
        logger.info("【SolutionGenerationNode】开始执行")

        intent = state.get("intent")
        messages = state.get("messages", [])

        # 提取用户问题（最后一条用户消息）
        user_question = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_question = m.get("content", "")
                break

        # 1. 从知识库检索（如已配置 RAG）
        rag_context = ""
        if self.rag:
            try:
                rag_context = await self.rag.search_and_format(user_question, top_k=3)
                logger.info(f"RAG 检索完成，上下文长度: {len(rag_context)}")
            except Exception as e:
                logger.warning(f"RAG 检索失败: {e}")

        # 2. 构造 Prompt
        prompt = self._build_reply_prompt(intent, user_question, rag_context)

        # 3. 调用 LLM 生成回复
        try:
            reply = await self.llm.complete(prompt, temperature=0.7)
            confidence = 0.85
        except Exception as e:
            logger.error(f"方案生成失败: {e}")
            reply = "抱歉，我暂时无法处理您的问题，已为您准备转接人工客服。"
            confidence = 0.0

        logger.info(f"回复生成完成，长度: {len(reply)}")

        # 4. 组装回复
        messages = list(messages)
        messages.append({"role": "assistant", "content": reply})

        # 5. 如果置信度低且不是无关输入，附加转人工选项
        status = "active"
        if confidence < 0.6 and intent not in ("unknown", "off_topic", "greeting"):
            status = "awaiting_choice"
            messages.append({
                "role": "assistant",
                "content": "\n\n如果以上回复没有解决您的问题，您可以选择：\n1. 转接人工客服\n2. 换个方式描述问题\n3. 留下联系方式，稍后回电",
            })

        return {
            "messages": messages,
            "solution_confidence": confidence,
            "status": status,
        }

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _build_reply_prompt(
        self,
        intent: Optional[str],
        user_question: str,
        rag_context: str,
    ) -> str:
        """构造回复生成 Prompt"""

        # 意图中文名映射
        intent_names = {
            "technical": "技术支持",
            "account": "账号问题",
            "billing": "计费问题",
            "feature": "功能咨询",
            "supplement": "补充咨询",
            "greeting": "问候",
            "off_topic": "无关问题",
            "manual": "人工服务",
            "unknown": "未知问题",
        }
        intent_name = intent_names.get(intent, "用户咨询")

        rag_section = ""
        if rag_context:
            rag_section = f"""
【相关知识库内容】
{rag_context}
"""

        return f"""你是专业的客服助手，正在处理一个{intent_name}类咨询。

【用户问题】
{user_question}
{rag_section}
【任务】
请根据用户问题，提供清晰、具体、有帮助的回复。
要求：
1. 直接回答用户问题，不要反问
2. 如果涉及操作步骤，请按序号列出
3. 语言简洁友好
4. 如果知识库内容有帮助，请结合使用
5. 如果不确定答案，诚实告知并建议转人工

请直接输出回复内容："""
