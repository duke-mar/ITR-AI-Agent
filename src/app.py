"""
ITR 智能客服机器人 —— FastAPI + WebSocket 入口

职责：
  1. HTTP 接口（健康检查、配置查看）
  2. WebSocket 实时对话
  3. 会话生命周期管理（创建/加载/保存）
  4. LangGraph 执行驱动

设计原则：
  - 不嵌入任何业务判断，全部委托给 Node / Graph
  - 特殊交互（满意度/选择）识别后调用 Node 方法处理
"""

import json
import logging
import os
from re import T
import sys
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# 把项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# 配置加载
# ============================================================
from config import settings, IntentRegistry

# ============================================================
# 核心模块
# ============================================================
from core.graph_builder import GraphBuilder
from core.skill_registry import SkillRegistry, skill_registry
from core.state import create_initial_state

# ============================================================
# Skill 模块
# ============================================================
from skills.llm_skill import LLMSkill
from skills.rag_skill import DifyRAGSkill, RAGFlowSkill
from skills.db_skill import DBSkill

# ============================================================
# Node 模块
# ============================================================
from nodes.intent_recognition import IntentRecognitionNode
from nodes.solution_generation import SolutionGenerationNode
from nodes.session_end import SessionEndNode

# ============================================================
# 日志配置（支持颜色 + 文件输出）
# ============================================================

class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    # ANSI 颜色代码
    COLORS = {
        "DEBUG": "\033[36m",      # 青色
        "INFO": "\033[32m",       # 绿色
        "WARNING": "\033[33m",    # 黄色
        "ERROR": "\033[31m",      # 红色
        "CRITICAL": "\033[35m",   # 紫色
    }
    RESET = "\033[0m"

    def format(self, record):
        # 给日志级别名添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def _setup_logging() -> logging.Logger:
    """初始化日志配置：终端彩色输出 + 文件持久化"""
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "itr_agent.log")

    # 创建根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 清除已有的处理器（避免重复）
    root_logger.handlers = []

    # 1. 终端处理器（带颜色）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = ColoredFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # 2. 文件处理器（无颜色，纯文本）
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)

    return logging.getLogger(__name__)


logger = _setup_logging()

# ============================================================
# 服务初始化
# ============================================================

def _init_skills() -> SkillRegistry:
    """初始化所有 Skill"""
    registry = SkillRegistry()

    # 1. LLM Skill（必填）
    llm = LLMSkill(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
    registry.register("llm", llm)

    # 2. RAG Skill（可选）
    if settings.RAG_ENABLED:
        # 根据配置选择具体实现（预留扩展点）
        rag = DifyRAGSkill(
            base_url=settings.RAG_BASE_URL,
            api_key=settings.RAG_API_KEY,
            top_k=settings.RAG_TOP_K,
        )
        registry.register("rag", rag)
        logger.info("RAG Skill 已启用")
    else:
        logger.info("RAG Skill 已禁用（如需启用请配置 .env）")

    # 3. DB Skill（可选）
    if settings.DB_ENABLED:
        db = DBSkill(
            db_url=settings.DB_URL,
            echo=settings.DB_ECHO,
        )
        registry.register("db", db)
        logger.info("DB Skill 已启用")
    else:
        logger.info("DB Skill 已禁用（如需启用请配置 .env）")

    return registry


def _init_graph(registry: SkillRegistry) -> Any:
    """初始化 LangGraph"""
    global intent_registry
    llm = registry.get("llm")
    rag = registry.get("rag")
    db = registry.get("db")

    # 加载业务配置（提升到模块级别，供路由处理器使用）
    intent_registry = IntentRegistry()

    # 创建 Node 实例（注入配置）
    # 注意：info_collection 节点已移除，追问逻辑集成到 intent_recognition 中
    nodes = [
        IntentRecognitionNode(llm=llm, intent_registry=intent_registry),
        SolutionGenerationNode(llm=llm, rag=rag),
        SessionEndNode(db=db),
    ]

    # 构建 Graph
    builder = GraphBuilder(
        skill_registry=registry,
        nodes=nodes,
        use_checkpoint=True,
    )
    return builder.build()


# 全局初始化
skill_registry = _init_skills()
graph = _init_graph(skill_registry)
logger.info("服务初始化完成")

# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(title=settings.APP_NAME, version="1.0.0")

# 静态文件（前端页面放在 static/ 目录）
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端聊天页面"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>ITR 智能客服</h1><p>请确保 static/index.html 存在</p>"


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "llm": skill_registry.get("llm") is not None,
        "rag": skill_registry.get("rag") is not None,
        "db": skill_registry.get("db") is not None,
    }


@app.get("/config")
async def get_config():
    """查看当前配置（不包含敏感信息）"""
    return {
        "app_name": settings.APP_NAME,
        "llm_model": settings.LLM_MODEL,
        "llm_base_url": settings.LLM_BASE_URL,
        "rag_enabled": settings.RAG_ENABLED,
        "db_enabled": settings.DB_ENABLED,
        "max_info_rounds": settings.MAX_INFO_COLLECTION_ROUNDS,
        "max_total_rounds": settings.MAX_TOTAL_ROUNDS,
    }


# ============================================================
# WebSocket 会话管理
# ============================================================

class ConnectionManager:
    """管理 WebSocket 连接与会话状态"""

    def __init__(self):
        self.connections: Dict[WebSocket, str] = {}
        self.session_states: Dict[str, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.connections[websocket] = session_id
        self.session_states[session_id] = create_initial_state()
        self.session_states[session_id]["session_id"] = session_id
        logger.info(f"WebSocket 连接建立: {session_id}")
        return session_id

    def disconnect(self, websocket: WebSocket):
        session_id = self.connections.pop(websocket, None)
        if session_id:
            state = self.session_states.pop(session_id, {})
            # 异步保存到数据库（如已配置）
            logger.info(f"WebSocket 连接断开: {session_id}")

    def get_state(self, session_id: str) -> Dict[str, Any]:
        return self.session_states.get(session_id, create_initial_state())

    def set_state(self, session_id: str, state: Dict[str, Any]):
        self.session_states[session_id] = state


manager = ConnectionManager()


# ============================================================
# WebSocket 消息处理
# ============================================================

async def _setup_session(websocket: WebSocket) -> str:
    """建立 WebSocket 会话，发送欢迎语"""
    session_id = await manager.connect(websocket)
    state = manager.get_state(session_id)

    welcome = "您好！我是 ITR 智能客服，请问有什么可以帮您？"
    state["messages"].append({"role": "assistant", "content": welcome})
    manager.set_state(session_id, state)
    await websocket.send_json({"type": "welcome", "content": welcome})

    return session_id


def _parse_message(raw: str) -> Dict[str, Any]:
    """解析前端发来的消息"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "text", "content": raw}


async def _handle_field_fill(
    websocket: WebSocket,
    state: Dict[str, Any],
    msg: Dict[str, Any],
    session_id: str,
) -> bool:
    """
    处理用户点击选项卡片（B类字段）。
    直接写入 collected_info，然后重新进入 Graph 检查是否还有缺失字段。
    """
    field_id = msg.get("field_id")
    value = msg.get("value")
    if not field_id or value is None:
        return False

    # 直接写入字段值
    state["collected_info"] = state.get("collected_info", {})
    state["collected_info"][field_id] = value
    manager.set_state(session_id, state)
    logger.info(f"[{session_id}] 字段填充: {field_id} = {value}")

    # 重新进入 Graph 检查是否还有缺失字段
    try:
        config = {"configurable": {"thread_id": session_id}}
        result = await graph.ainvoke(state, config=config)
        state.update(result)
        manager.set_state(session_id, state)
        await _send_response(websocket, state)
    except Exception as e:
        logger.exception(f"[{session_id}] LangGraph 执行异常: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"系统处理出错，请稍后再试。错误：{str(e)}",
        })

    return True

async def _handle_repeat_manual(
    websocket: WebSocket,
    state: Dict[str, Any],
    session_id: str,
) -> bool:
    """处理用户排队中重复转人工，提示正在排队中！"""
    
    # 把取消消息写入对话历史，让 LLM 知道用户已放弃转人工
    repeat_reply = "已为您转接人工客服，请稍等，正在为您排队..."
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": repeat_reply})
    state["messages"] = messages
    manager.set_state(session_id, state)
    await websocket.send_json({
        "type": "manual_queue",
        "content": repeat_reply,
    })
    return True


async def _handle_cancel_manual(
    websocket: WebSocket,
    state: Dict[str, Any],
    session_id: str,
) -> bool:
    """处理用户取消人工排队，同时重置追问状态，允许用户开启新话题。"""
    state["status"] = "active"
    state["retry_count"] = 0
    state["interactive"] = None
    state["info_complete"] = False
    state["end_reason"] = None
    # 意图也清空，让下一条消息被当作全新咨询处理
    state["intent"] = None
    # 把取消消息写入对话历史，让 LLM 知道用户已放弃转人工
    cancel_reply = "已取消人工排队，请问还有什么可以帮您？"
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": cancel_reply})
    state["messages"] = messages
    manager.set_state(session_id, state)
    await websocket.send_json({
        "type": "reply",
        "content": cancel_reply,
    })
    return True


async def _handle_rule_validation(
    websocket: WebSocket,
    state: Dict[str, Any],
    msg: Dict[str, Any],
    session_id: str,
) -> bool:
    """
    处理规则字段（C类）的正则验证。
    验证成功：写入字段，直接调用 Graph 检查是否还有缺失字段。
    验证失败：根据失败次数返回不同级别的错误提示。
    """
    # 优先从消息中读取 field_id（前端提交时带上更可靠），其次从 state 推断
    current_field = msg.get("field_id") or _get_current_asking_field(state)
    if not current_field:
        return False  # 当前没有追问规则字段

    field_config = intent_registry.get_rule_config(
        state.get("intent", ""), current_field
    )
    if not field_config:
        return False  # 当前字段不是规则字段

    user_content = msg.get("content", "")
    import re
    match = re.search(field_config["pattern"], user_content)

    if match:
        # 正则匹配成功，写入字段，重置失败计数，直接调用 Graph
        state["collected_info"] = state.get("collected_info", {})
        state["collected_info"][current_field] = match.group(0)
        state["retry_count"] = 0
        manager.set_state(session_id, state)
        logger.info(f"[{session_id}] 规则字段匹配成功: {current_field} = {match.group(0)}")

        # 直接调用 Graph 检查是否还有缺失字段（不复用 _handle_field_fill 避免重复 save）
        try:
            config = {"configurable": {"thread_id": session_id}}
            result = await graph.ainvoke(state, config=config)
            state.update(result)
            manager.set_state(session_id, state)
            await _send_response(websocket, state)
        except Exception as e:
            logger.exception(f"[{session_id}] LangGraph 执行异常: {e}")
            await websocket.send_json({
                "type": "error",
                "content": f"系统处理出错，请稍后再试。错误：{str(e)}",
            })
        return True

    # 正则匹配失败
    retry_count = state.get("retry_count", 0) + 1
    state["retry_count"] = retry_count
    manager.set_state(session_id, state)
    logger.info(f"[{session_id}] 规则字段匹配失败: {current_field}, 第{retry_count}次")

    # 根据失败次数返回不同级别的错误提示
    if retry_count >= 5:
        # 超过5次，强行转人工
        await websocket.send_json({
            "type": "force_manual",
            "content": "已为您转接人工客服，正在排队中...",
            "show_cancel_button": True,
        })
    elif retry_count >= 3:
        # 超过3次，提示带转人工选项
        await websocket.send_json({
            "type": "error_hint_with_manual",
            "field_id": current_field,
            "content": "您输入的格式有误，无法识别，请重新按照样例格式输入，或选择转接人工客服",
            "example": field_config.get("example", ""),
            "retry_count": retry_count,
        })
    else:
        # 1-2次，普通错误提示
        await websocket.send_json({
            "type": "error_hint",
            "field_id": current_field,
            "content": "您输入的格式不对，无法识别，请重新按照样例格式输入",
            "example": field_config.get("example", ""),
            "retry_count": retry_count,
        })

    return True  # 验证失败，已发送错误提示，不再进入 Graph


async def _handle_normal_flow(
    websocket: WebSocket,
    state: Dict[str, Any],
    user_content: str,
    session_id: str,
) -> None:
    """正常对话流程：用户消息进入 LangGraph 处理"""
    state["messages"].append({"role": "user", "content": user_content})
    state["round_count"] = state.get("round_count", 0) + 1
    manager.set_state(session_id, state)

    try:
        config = {"configurable": {"thread_id": session_id}}
        result = await graph.ainvoke(state, config=config)
        state.update(result)
        
        manager.set_state(session_id, state)
        await _send_response(websocket, state)
    except Exception as e:
        logger.exception(f"[{session_id}] LangGraph 执行异常: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"系统处理出错，请稍后再试。错误：{str(e)}",
        })


def _is_manual_request(text: str) -> bool:
    """判断用户是否要求转人工"""
    keywords = ["人工", "客服", "转人工", "人工客服", "找人工", "接人工", "投诉", "我要投诉", "找你们领导"]
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def _is_cancel_or_done(text: str) -> bool:
    """判断用户是否想结束当前追问"""
    keywords = ["取消", "算了", "不要了", "不用了", "跳过", "没有", "没了", "没有了", "不填了", "不知道"]
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def _is_strong_cancel(text: str) -> bool:
    """判断用户是否明确不想继续回答（用于规则字段追问时，避免'算了'被误触发）"""
    strong_keywords = ["没有", "没了", "没有了", "不知道", "不填了", "不想填", "跳过"]
    lowered = text.lower()
    return any(kw in lowered for kw in strong_keywords)

def _is_manual_request(text: str) -> bool:
    """判断用户是否要求转人工"""
    manual_keywords = ["人工", "客服", "转人工", "人工客服", "找人工", "接人工", "投诉", "强制人工", "强制转人工", "强制人工客服", "强制接人工", "强制投诉", "我要强制投诉", "强制找你们领导"]
    is_manual = any(kw in text for kw in manual_keywords)
    return is_manual

def _is_cancel_manual_request(text: str) -> bool:
    """判断用户是否想取消人工排队"""
    keywords = ["取消", "算了", "不排队了", "取消人工", "取消排队", "不等了"]
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def _looks_like_new_intent(text: str) -> bool:
    """
    判断用户输入是否像是一个全新的问题/意图，
    而不是在回答当前追问的字段值。
    """
    # 包含问句特征（明显在提问而不是填字段）
    question_marks = ["?", "？", "怎么", "怎么办", "如何", "为什么", "请问", "怎样"]
    if any(q in text for q in question_marks):
        return True
    # 输入较长（超过 15 字），不太可能是简单的字段值
    if len(text) > 15:
        return True
    # 包含常见业务意图关键词
    intent_keywords = ["报错", "错误", "系统", "功能", "使用", "咨询", "问题", "帮助", "升级", "套餐", "账号", "密码", "登录", "注册", "忘记密码", "修改", "绑定", "解绑"]
    if any(kw in text for kw in intent_keywords):
        return True
    # 包含明显的闲聊/无关关键词（off_topic）
    off_topic_keywords = ["天气", "时间", "新闻", "股票", "彩票", "娱乐", "明星", "电影", "游戏", "吃饭", "好吃", "好玩"]
    if any(kw in text for kw in off_topic_keywords):
        return True
    return False


async def _mark_info_complete_and_proceed(
    websocket: WebSocket,
    state: Dict[str, Any],
    session_id: str,
) -> None:
    """
    用户表示不再补充，将剩余缺失字段填为"用户未提供"，
    标记信息完整，然后调用 Graph 进入方案生成。
    """
    intent = state.get("intent")
    collected = dict(state.get("collected_info", {}))

    if intent and intent_registry:
        intent_config = intent_registry.get(intent)
        if intent_config:
            for field in intent_config.get_all_fields():
                if collected.get(field.id) is None:
                    collected[field.id] = "用户未提供"

    state["collected_info"] = collected
    state["interactive"] = None
    state["info_complete"] = True
    manager.set_state(session_id, state)
    logger.info(f"[{session_id}] 用户跳过追问，缺失字段填为'用户未提供'，进入方案生成")

    try:
        config = {"configurable": {"thread_id": session_id}}
        result = await graph.ainvoke(state, config=config)
        state.update(result)
        manager.set_state(session_id, state)
        await _send_response(websocket, state)
    except Exception as e:
        logger.exception(f"[{session_id}] LangGraph 执行异常: {e}")
        await websocket.send_json({
            "type": "error",
            "content": f"系统处理出错，请稍后再试。错误：{str(e)}",
        })


async def _dispatch_message(
    websocket: WebSocket,
    state: Dict[str, Any],
    msg: Dict[str, Any],
    session_id: str,
) -> bool:
    """
    消息分发器。
    按优先级依次处理各类消息，返回 True 表示已处理，False 表示继续后续流程。
    """
    msg_type = msg.get("type", "text")
    user_content = msg.get("content", "")
    interactive = state.get("interactive")
    status = state.get("status")
    logger.info(f"[{session_id}]-消息分发处理----- 收到消息: {msg_type} - {user_content}")
    # 优先级-1：人工排队状态
    if status in ("transferred", "manual_queue"):
        if _is_cancel_manual_request(user_content) or msg_type == "cancel_manual":
            return await _handle_cancel_manual(websocket, state, session_id)
        else:
            # 用户没有明确取消人工排队，且用户意图时转人工（排队场景下，用户输入转人工关键词，不取消排队再排队，而是给给提示正在排队中！）----
            if _is_manual_request(user_content):    
                # 用户输入了非取消内容（如新问题），自动取消排队并处理
                await _handle_repeat_manual(websocket, state, session_id)
                return True

        # 用户输入了非取消内容（如新问题），自动取消排队并处理
        logger.info(f"[{session_id}] 排队状态下收到非取消输入，自动取消排队: {user_content[:30]}")
        await _handle_cancel_manual(websocket, state, session_id)
        # 重新加载已重置的状态，继续处理用户输入
        state = manager.get_state(session_id)
        await _handle_normal_flow(websocket, state, user_content, session_id)
        return True

    # 优先级0：追问状态下的特殊输入（必须在规则验证和 normal flow 之前处理）
    if interactive and msg_type == "text":
        interactive_type = interactive.get("type")

        # 0a. 转人工请求 —— 清除追问状态，让 LLM 重新识别 manual 意图
        if _is_manual_request(user_content):
            state["interactive"] = None
            manager.set_state(session_id, state)
            logger.info(f"[{session_id}] 追问状态下收到转人工请求，清除追问状态")
            await _handle_normal_flow(websocket, state, user_content, session_id)
            return True

        # 0b. 用户不想继续回答
        #    - 选项卡片追问：允许"取消/算了/没有"等词跳过
        #    - 规则字段追问：只允许"没有/没了/不知道"等明确否定词跳过，"算了"走格式验证
        should_skip = False
        if interactive_type == "ask_options":
            should_skip = _is_cancel_or_done(user_content)
        elif interactive_type == "ask_input":
            should_skip = _is_strong_cancel(user_content)

        if should_skip:
            await _mark_info_complete_and_proceed(websocket, state, session_id)
            return True

        # 0c. 用户在追问时输入了明显的新问题 —— 清除追问状态，让 LLM 重新识别意图
        if _looks_like_new_intent(user_content):
            state["interactive"] = None
            manager.set_state(session_id, state)
            logger.info(f"[{session_id}] 追问状态下收到新意图输入，清除追问状态: {user_content[:30]}")
            await _handle_normal_flow(websocket, state, user_content, session_id)
            return True

    # 优先级1：用户点击选项卡片（B类字段）
    if msg_type == "field_fill":
        return await _handle_field_fill(websocket, state, msg, session_id)

    # 优先级2：取消人工排队
    if msg_type == "cancel_manual":
        return await _handle_cancel_manual(websocket, state, session_id)

    # 优先级3：特殊交互（满意度/选择）
    if msg_type == "satisfaction" or status == "awaiting_satisfaction":
        await _handle_satisfaction(websocket, state, user_content, session_id)
        return True

    if msg_type == "choice" or status == "awaiting_choice":
        await _handle_choice(websocket, state, msg, session_id)
        return True

    # 优先级4：规则字段验证（C类字段）
    handled = await _handle_rule_validation(websocket, state, msg, session_id)
    if handled:
        return True

    # 优先级5：正常对话流程
    await _handle_normal_flow(websocket, state, user_content, session_id)
    return True


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 主入口，只保留流程控制"""
    session_id = await _setup_session(websocket)

    try:
        while True:
            # 接收用户消息
            raw = await websocket.receive_text()
            logger.info(f"[{session_id}] 收到消息: {raw}")

            # 解析消息
            msg = _parse_message(raw)

            # 加载最新状态
            state = manager.get_state(session_id)

            # 分发处理
            await _dispatch_message(websocket, state, msg, session_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.exception(f"WebSocket 异常: {e}")
        manager.disconnect(websocket)


# ============================================================
# 辅助函数
# ============================================================

def _get_current_asking_field(state: Dict[str, Any]) -> Optional[str]:
    """
    获取当前正在追问的字段。
    优先从 interactive 指令中读取（最准确），
    其次从 collected_info 中找到第一个值为 None 的字段。
    """
    interactive = state.get("interactive")
    if interactive and interactive.get("field_id"):
        return interactive["field_id"]

    collected = state.get("collected_info", {})
    for field_id, value in collected.items():
        if value is None:
            return field_id
    return None


async def _send_response(websocket, state: Dict[str, Any]) -> None:
    """
    发送响应给前端。
    优先处理 interactive 指令（选项卡片、规则输入框），
    其次处理普通文本回复。
    """
    # 检查是否有 interactive 指令
    interactive = state.get("interactive")
    if interactive:
        logger.info(f"_send_response 发送 选项卡片>interactive 指令: {interactive}")
        await websocket.send_json(interactive)
        return
    
    # 提取最后一条助手回复
    last_reply = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "assistant":
            last_reply = m.get("content", "")
            break

    if last_reply:
        status = state.get("status")
        # 人工排队状态使用特殊消息类型，让前端显示取消按钮,---若状态为人工排队，则type改为 manual_queue
        msg_type = "manual_queue" if status == "manual_queue" else "reply"
        logger.info(f"_send_response 发送 普通文本回复>reply 指令: {last_reply}")

        await websocket.send_json({
            "type": msg_type,
            "content": last_reply,
            "intent": state.get("intent"),
            "status": status,
            "round_count": state.get("round_count"),
        })

    # 如果进入结束状态，给前端提示
    if state.get("status") in ("awaiting_satisfaction", "awaiting_choice"):
        logger.info(f"_send_response 发送 状态变更>status_change 指令: {state.get('status')}")
        await websocket.send_json({
            "type": "status_change",
            "status": state.get("status"),
        })


# ============================================================
# 特殊交互处理器
# ============================================================

async def _handle_satisfaction(websocket, state, user_content, session_id):
    """处理满意度评分"""
    try:
        score = int(user_content)
        if not 1 <= score <= 5:
            raise ValueError("范围错误")
    except ValueError:
        await websocket.send_json({
            "type": "reply",
            "content": "请输入 1 到 5 之间的数字。",
        })
        return

    node = SessionEndNode()
    updates = node.handle_satisfaction(state, score)
    state.update(updates)
    manager.set_state(session_id, state)

    await websocket.send_json({
        "type": "reply",
        "content": state["messages"][-1]["content"],
        "status": state["status"],
    })


async def _handle_choice(websocket, state, msg, session_id):
    """处理转人工选择（1/2/3）"""
    choice = str(msg.get("content", "")).strip()
    extra = msg.get("extra", "")

    node = SessionEndNode()
    updates = node.handle_user_choice(state, choice, extra)
    state.update(updates)
    manager.set_state(session_id, state)

    await websocket.send_json({
        "type": "reply",
        "content": state["messages"][-1]["content"],
        "status": state["status"],
    })

    # 如果用户选 2（重新描述），告诉前端重置状态
    if choice == "2":
        await websocket.send_json({
            "type": "status_change",
            "status": "active",
            "reset": True,
        })


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn

    port = settings.APP_PORT
    print("=" * 60)
    print(f"  {settings.APP_NAME} v1.0")
    print("=" * 60)
    print(f"  LLM 模型: {settings.LLM_MODEL}")
    print(f"  LLM 地址: {settings.LLM_BASE_URL}")
    print(f"  RAG 状态: {'已启用' if settings.RAG_ENABLED else '已禁用'}")
    print(f"  DB  状态: {'已启用' if settings.DB_ENABLED else '已禁用'}")
    print("=" * 60)
    print(f"  访问地址: http://localhost:{port}")
    print(f"  API 文档: http://localhost:{port}/docs")
    print(f"  WebSocket: ws://localhost:{port}/ws")
    print("=" * 60)

    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=port,
        reload=settings.APP_DEBUG,
        log_level="info",
    )
