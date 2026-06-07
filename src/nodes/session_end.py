"""
会话结束 Node

职责：
  - 处理会话结束前的收尾工作
  - 保存会话记录到数据库
  - 收集满意度评分（如需要）
  - 处理转人工、留联系方式等分支

业务规则：
  - 信息收集失败 → 友好结束，建议转人工
  - 方案已给出 → 询问满意度
  - 用户要求人工 → 记录转人工原因
"""

import logging
from typing import Any, Dict, List, Optional

from core.node_interface import INode
from core.state import ITRState
from skills.db_skill import DBSkill

logger = logging.getLogger(__name__)


class SessionEndNode(INode):
    """会话结束 Node"""

    name = "session_end"

    def __init__(self, db: Optional[DBSkill] = None):
        self.db = db

    def required_skills(self):
        skills = []
        if self.db:
            skills.append(DBSkill)
        return skills

    async def execute(self, state: ITRState) -> Dict[str, Any]:
        """执行会话结束"""
        logger.info("=" * 50)
        logger.info("【SessionEndNode】开始执行")

        end_reason = state.get("end_reason")
        status = state.get("status")
        intent = state.get("intent")

        # 根据结束原因生成不同的结束语
        if intent == "manual" or end_reason == "manual":
            reply = "已为您转接人工客服，请稍等，正在为您排队..."
        elif end_reason == "info_failed":
            reply = "抱歉，由于信息收集不完整，暂时无法为您提供解决方案。已为您记录问题，客服将尽快联系您。"
        elif status == "awaiting_choice":
            reply = "感谢您的反馈，会话已结束。如有其他问题，欢迎随时咨询。"
        elif intent in ("unknown", "off_topic"):
            reply = "抱歉，我不太理解您的问题。请问有什么可以帮您的？您可以尝试描述具体问题，或输入'人工'转接客服。"
        else:
            reply = "感谢您的咨询，祝您使用愉快！如果还有其他问题，随时找我。"

        messages = list(state.get("messages", []))
        messages.append({"role": "assistant", "content": reply})

        # 保存会话到数据库（如已配置）
        if self.db:
            try:
                session_id = state.get("session_id", "unknown")
                await self.db.save_session(session_id, dict(state))
                logger.info(f"会话已持久化: {session_id}")
            except Exception as e:
                logger.error(f"会话持久化失败: {e}")

        logger.info("会话结束")

        # 转人工时保持排队状态，方便用户后续取消
        if intent == "manual" or end_reason == "manual":
            new_status = "manual_queue"
        else:
            new_status = "ended"

        return {
            "messages": messages,
            "status": new_status,
            "end_reason": end_reason or "solved",
        }

    # ------------------------------------------------------------------
    # 便捷方法（供 app.py 直接调用）
    # ------------------------------------------------------------------

    def handle_satisfaction(self, state: ITRState, score: int) -> Dict[str, Any]:
        """处理满意度评分（供 app.py 特殊交互调用）"""
        messages = list(state.get("messages", []))
        messages.append({
            "role": "assistant",
            "content": f"感谢您的评价（{score}分）！会话已结束。",
        })

        return {
            "messages": messages,
            "satisfaction": score,
            "status": "ended",
            "end_reason": "solved",
        }

    def handle_user_choice(
        self,
        state: ITRState,
        choice: str,
        extra: str = "",
    ) -> Dict[str, Any]:
        """处理转人工选择（供 app.py 特殊交互调用）"""
        messages = list(state.get("messages", []))

        if choice == "1":
            # 转人工
            messages.append({
                "role": "assistant",
                "content": "已为您转接人工客服，请稍等...",
            })
            return {
                "messages": messages,
                "status": "transferred",
                "end_reason": "manual",
            }

        elif choice == "2":
            # 重新描述
            messages.append({
                "role": "assistant",
                "content": "好的，请重新描述您的问题。",
            })
            return {
                "messages": messages,
                "status": "active",
                "info_collection_round": 0,
                "round_count": 0,
                "collected_info": {},
                "intent": None,
                "end_reason": None,
                "info_complete": False,
            }

        elif choice == "3":
            # 留联系方式
            messages.append({
                "role": "assistant",
                "content": f"已记录您的联系方式（{extra}），客服将尽快回电。",
            })
            return {
                "messages": messages,
                "contact_info": extra,
                "status": "callback_pending",
                "end_reason": "manual",
            }

        else:
            messages.append({
                "role": "assistant",
                "content": "已记录，会话结束。",
            })
            return {
                "messages": messages,
                "status": "ended",
            }
