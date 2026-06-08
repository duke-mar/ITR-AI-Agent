"""
LangGraph 编排器

职责：
  - 注册所有 Node（只绑定 execute 方法）
  - 集中配置路由规则（条件跳转）
  - 管理 Checkpoint（MemorySaver）
  - 启动时校验 Node 的 Skill 依赖

设计原则：
  - 不碰业务逻辑
  - 不构造 Prompt
  - 不调用外部服务
"""

import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import ITRState
from .node_interface import INode
from .skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


class GraphBuilder:
    """LangGraph 图构建器"""

    def __init__(
        self,
        skill_registry: SkillRegistry,
        nodes: Optional[List[INode]] = None,
        use_checkpoint: bool = True,
    ):
        self.skill_registry = skill_registry
        self.nodes: Dict[str, INode] = {}
        self.use_checkpoint = use_checkpoint

        # 注册传入的 Node
        if nodes:
            for node in nodes:
                self.register_node(node)

    def register_node(self, node: INode) -> None:
        """注册一个 Node，并校验其 Skill 依赖"""
        if node.name in self.nodes:
            logger.warning(f"Node '{node.name}' 已被注册，将被覆盖")

        # 校验依赖
        missing = self.skill_registry.validate_node_dependencies(node)
        if missing:
            raise RuntimeError(
                f"Node '{node.name}' 依赖的 Skill 未注册: {', '.join(missing)}"
            )

        self.nodes[node.name] = node
        logger.info(f"Node 注册成功: {node.name}")

    def build(self) -> Any:
        """
        构建并返回可执行的 LangGraph。

        Returns:
            Compiled StateGraph 实例
        """
        if not self.nodes:
            raise RuntimeError("没有注册任何 Node，无法构建 Graph")

        # 创建状态图
        workflow = StateGraph(ITRState)

        # 1. 注册所有 Node（只绑定 execute）
        for name, node in self.nodes.items():
            workflow.add_node(name, self._wrap_node(node))
            logger.info(f"GraphBuilder: 节点已注册 -> {name}")

        # 2. 配置条件路由（集中管理）
        self._setup_routes(workflow)

        # 3. 设置入口点
        if "intent_recognition" not in self.nodes:
            raise RuntimeError(
                "缺少入口节点 'intent_recognition'。请确保已注册意图识别 Node。"
            )
        workflow.set_entry_point("intent_recognition")

        # 4. 编译（可选 Checkpoint）
        checkpointer = MemorySaver() if self.use_checkpoint else None
        compiled = workflow.compile(checkpointer=checkpointer)
        logger.info(f"GraphBuilder: LangGraph 编译完成 (checkpoint={self.use_checkpoint})")
        return compiled

    # ------------------------------------------------------------------
    # 内部包装器
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_node(node: INode):
        """包装 Node 的 execute 方法，适配 LangGraph 调用签名"""
        async def _node(state: ITRState) -> Dict[str, Any]:
            try:
                updates = await node.execute(state)
                # 确保返回 dict
                if not isinstance(updates, dict):
                    logger.error(
                        f"Node '{node.name}' execute 返回非 dict: {type(updates)}"
                    )
                    return {}
                # 自动标记 last_node
                updates["last_node"] = node.name
                return updates
            except Exception as e:
                logger.exception(f"节点 '{node.name}' 执行异常: {e}")
                return {}

        return _node

    # ------------------------------------------------------------------
    # 路由配置（集中管理，Node 完全不碰路由）
    # ------------------------------------------------------------------

    def _setup_routes(self, workflow: StateGraph) -> None:
        """配置所有条件路由边"""
        # 注意：info_collection 节点已移除
        # 追问逻辑集成在 intent_recognition 中，直接生成 interactive 指令

        # intent_recognition -> 各分支
        if "intent_recognition" in self.nodes:
            workflow.add_conditional_edges(
                "intent_recognition",
                self._route_intent,
            )

        # solution_generation -> 各分支
        if "solution_generation" in self.nodes:
            workflow.add_conditional_edges(
                "solution_generation",
                self._route_solution,
            )

        # session_end -> 结束
        if "session_end" in self.nodes:
            workflow.add_conditional_edges(
                "session_end",
                self._route_end,
            )

    def _route_intent(self, state: ITRState) -> str:
        """
        意图识别后的路由逻辑（追问集成在 intent_recognition 中）。

        返回目标节点名，或 LangGraph 的 END 常量。
        """
        intent = state.get("intent")
        status = state.get("status")
    
        # 人工排队中：不再生成新方案或追问，等待客服接入
        if status in ("transferred", "manual_queue"):
            logger.info(f"路由: 状态={status} -> END (排队中)")
            return END

        # 无关输入：已在意图识别节点拦截并回复，直接结束
        if intent == "off_topic":
            logger.info("路由: off_topic -> END")
            return END

        # 兜底：如果 LLM 判为 manual，但用户最近一次输入明显不是转人工
        # （如刚取消人工后输入了业务问题），避免受历史消息影响重复触发转人工
        if intent == "manual":
            decrease_level_intent = state.get("decrease_level_intent")
            if decrease_level_intent == "solution_generation":
                logger.info(f"路由: manual 但用户最近输入'{last_user}'不含转人工关键词，忽略 -> solution_generation")
                return "solution_generation"
            logger.info("路由: manual -> session_end")
            return "session_end"
            
        # 如果有 interactive 指令（追问），本轮结束，等待用户回复
        if state.get("interactive"):
            logger.info("路由: 有追问指令 -> END")
            return END

        # 信息已完整，进入方案生成
        if state.get("info_complete"):
            logger.info("路由: 信息完整 -> solution_generation")
            return "solution_generation"

        # 正常业务意图（technical/account/billing/feature）
        if intent:
            logger.info(f"路由: {intent} -> solution_generation")
            return "solution_generation"

        # 默认：未知意图也直接生成回复
        logger.info("路由: unknown -> solution_generation")
        return "solution_generation"

    def _route_solution(self, state: ITRState) -> str:
        """
        方案生成后的路由逻辑。
        """
        status = state.get("status")

        # 需要用户选择（转人工/继续/留联系方式）
        if status == "awaiting_choice":
            logger.info("路由: 等待用户选择 -> session_end")
            return "session_end"

        # 会话正常结束
        if status == "ended":
            logger.info("路由: 会话结束 -> session_end")
            return "session_end"

        # 默认：方案已给出，等待用户反馈
        logger.info("路由: 方案已发出 -> END")
        return END

    def _route_end(self, state: ITRState) -> str:
        """
        会话结束后的路由逻辑。
        """
        # session_end 之后直接结束整个图
        logger.info("路由: session_end -> END")
        return END
