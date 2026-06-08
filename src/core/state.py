"""
全局 State 定义

LangGraph 的 State 结构，所有 Node 共享此状态。
核心设计：
  - total=False 允许字段缺失，便于逐步补充
  - dict 类型字段需要自定义 Reducer 实现增量合并
"""

from typing import TypedDict, List, Dict, Any, Optional


def merge_dict(left: Dict, right: Dict) -> Dict:
    """
    自定义 Reducer：字典增量合并。
    LangGraph 默认对 dict 是覆盖（lambda x, y: y），
    这里改为递归合并，确保 collected_info 等字段不会丢失已有数据。
    """
    if not isinstance(left, dict) or not isinstance(right, dict):
        return right if right is not None else left

    result = dict(left)
    for key, value in right.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


class ITRState(TypedDict, total=False):
    """
    全局对话状态。

    保留变量（改名需全局同步）：
      - messages: 对话历史
      - intent: 当前意图
      - collected_info: 已收集字段（增量合并）
      - info_collection_round: 追问轮数
      - round_count: 总轮数
      - last_node: 上一个执行节点
      - status: 会话状态
      - info_complete: 信息是否完整
    """

    # ============================================================
    # 核心保留字段（多 Node 共享）
    # ============================================================
    messages: List[Dict[str, Any]]
    """对话历史，格式 [{"role": "user|assistant", "content": str}]"""

    intent: Optional[str]
    """当前意图标签，如 technical / account / billing / feature"""

    intent_confidence: float
    """意图置信度 0.0~1.0"""

    collected_info: Dict[str, Any]
    """已收集信息（key-value，增量合并，非覆盖）"""

    info_collection_round: int
    """信息收集已进行轮数"""

    round_count: int
    """当前总对话轮数"""

    last_node: Optional[str]
    """上一个执行的节点名"""

    next_node: Optional[str]
    """强制路由目标（Skill 可临时覆盖）"""

    # ============================================================
    # 流程控制字段
    # ============================================================
    status: str
    """会话状态: active / ended / transferred / callback_pending / awaiting_satisfaction / awaiting_choice"""

    info_complete: bool
    """信息收集是否完成"""

    retry_count: int
    """方案重试次数"""

    solution_confidence: Optional[float]
    """方案置信度"""

    supplement: Optional[str]
    """补充状态: none / ing / done"""

    interactive: Optional[Dict[str, Any]]
    """追问交互指令（选项卡片/规则输入框），无追问时为 None"""

    session_id: Optional[str]
    """会话 ID（WebSocket 连接时注入）"""

    # ============================================================
    # 业务数据字段（Node 可自由扩展）
    # ============================================================
    ticket_id: Optional[str]
    """工单号"""

    satisfaction: Optional[int]
    """满意度 1-5"""

    contact_info: Optional[str]
    """用户联系方式"""

    end_reason: Optional[str]
    """结束原因: solved / info_failed / retry_failed / round_limit / manual"""


def create_initial_state() -> ITRState:
    """创建全新会话的初始状态"""
    return {
        "messages": [],
        "intent": None,
        "supplement": "none",
        "intent_confidence": 0.0,
        "collected_info": {},
        "info_collection_round": 0,
        "round_count": 0,
        "retry_count": 0,
        "solution_confidence": 0.0,
        "status": "active",
        "ticket_id": None,
        "satisfaction": None,
        "contact_info": None,
        "end_reason": None,
        "last_node": None,
        "next_node": None,
        "info_complete": False,
        "decrease_level_intent": None     # 降级意图，若大模型将判断为人工，但用户并非选人工时可以这里控制
    }
