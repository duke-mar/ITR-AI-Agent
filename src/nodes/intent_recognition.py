"""
意图识别 Node

职责：
  1. 过滤用户消息（暴力、色情、政治、无关内容）
  2. 识别用户意图（technical/account/billing/feature/manual）
  3. 判断补充状态（none/ing/done）
  4. 第一轮提取开放文本字段（A类）
  5. 初始化所有字段（开放文本/枚举/规则）为 None
  6. 返回 State 更新片段

设计原则：
  - 所有业务数据从 IntentRegistry 读取
  - 代码中不硬编码任何中文业务数据
"""

import json
import logging
from typing import Any, Dict, List, Optional

from core.node_interface import INode
from core.state import ITRState
from skills.llm_skill import LLMSkill
from config.loader import IntentRegistry, OpenTextField, EnumField, RuleField

logger = logging.getLogger(__name__)


class IntentRecognitionNode(INode):
    """意图识别 Node"""

    name = "intent_recognition"

    # 系统级意图（不依赖配置）
    SYSTEM_INTENTS = ["greeting", "off_topic", "manual", "supplement"]

    def __init__(self, llm: LLMSkill, intent_registry: IntentRegistry):
        self.llm = llm
        self.intent_registry = intent_registry

    def required_skills(self):
        return [LLMSkill]

    # ------------------------------------------------------------------
    # 主执行逻辑
    # ------------------------------------------------------------------

    async def execute(self, state: ITRState) -> Dict[str, Any]:
        """
        执行意图识别（一站式处理）。

        职责：
          1. 过滤用户消息
          2. 识别意图和补充状态
          3. 初始化 collected_info
          4. 提取开放文本字段（A类）
          5. 检查缺失字段，生成追问指令（B类/C类）
          6. 标记信息是否完整

        注意：info_collection 节点已移除，追问逻辑集成在此。
        """
        logger.info("=" * 50)
        logger.info("【IntentRecognitionNode】开始执行")

        messages = state.get("messages", [])
        if not messages:
            logger.warning("无用户消息，跳过意图识别")
            return {"last_node": self.name}

        # 步骤1：过滤用户消息
        last_msg = self._get_last_user_message(messages)
        if not await self._filter_message(last_msg):
            reply = "抱歉，您输入的内容无法处理。如有问题请联系人工客服。"
            return {
                "messages": _append_assistant(messages, reply),
                "intent": "off_topic",
            }

        # 步骤2：调用 LLM 识别意图和补充状态
        intent_result = await self._recognize_intent(messages)
        intent = intent_result.get("intent", "unknown")
        supplement = intent_result.get("supplement", "none")
        logger.info(f"意图识别结果: intent={intent}, supplement={supplement}")

        # 兜底：如果 LLM 返回 unknown，但输入明显不是客服业务问题，强制改为 off_topic
        if intent == "unknown":
            # 无意义重复字符/乱码检测, 关键词过滤，可以升级为llm检测-----------------------！！！！！！！！！！！！！！！
            if self._is_gibberish(last_msg):
                logger.info(f"LLM 判为 unknown，但输入明显无意义，强制改为 off_topic: {last_msg[:50]}")
                intent = "off_topic"
                supplement = "none"
                updates = {"intent": intent, "supplement": supplement}
                return updates
            #  关键词过滤，可以升级为llm检测-----------------------！！！！！！！！！！！！！！！    
            if self._is_obviously_off_topic(last_msg):
                logger.info(f"LLM 判为 unknown，但输入明显无关，强制改为 off_topic: {last_msg[:50]}")
                intent = "off_topic"

        # 拦截无关输入，不进入后续节点
        if intent == "off_topic":
            reply = "抱歉，您输入的内容与客服咨询无关，我无法处理。如有问题请联系人工客服。"
            logger.info(f"拦截无关输入: {last_msg[:50]}")
            return {
                "messages": _append_assistant(messages, reply),
                "intent": "off_topic",
                "supplement": "none",
                "interactive": None,
            }

        # 兜底：如果 LLM 判为 manual，但用户最近一次输入明显不是转人工
        # （如刚取消人工后输入了业务问题），避免受历史消息影响重复触发转人工
        if intent == "manual":
            messages = state.get("messages", [])
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = m.get("content", "")
                    break
            # 只有用户最近一次输入明确包含转人工关键词，才真的转人工----------------------------------可升级为有llm判断意图
            manual_keywords = ["人工", "客服", "转人工", "人工客服", "找人工", "接人工", "投诉"]
            is_real_manual = any(kw in last_user for kw in manual_keywords)
            if not is_real_manual:
                logger.info(f"路由: manual 但用户最近输入'{last_user}'不含转人工关键词，忽略 -> solution_generation")
                decrease_level_intent = "solution_generation"    

        # 步骤3：组装基础更新
        updates: Dict[str, Any] = {
            "intent": intent,
            "decrease_level_intent": decrease_level_intent,
            "supplement": supplement,
        }

        # 步骤4：处理 collected_info（初始化 + 提取 + 追问）
        if intent in self.intent_registry.list_ids():
            # 4.1 初始化和提取
            collected_updates = self._handle_collected_info(state, intent, supplement, last_msg)
            updates.update(collected_updates)

            # 4.2 检查是否需要追问（info_collection 逻辑集成）
            if not updates.get("info_complete"):
                interactive = self._build_interactive(updates.get("collected_info", {}), intent)
                if interactive:
                    updates["interactive"] = interactive
                    logger.info(f"生成追问指令: {interactive['type']} - {interactive.get('field_id')}")
                else:
                    # 无缺失字段，清除可能残留的 interactive，避免死循环
                    updates["interactive"] = None
            else:
                # 信息已完整，清除 interactive
                updates["interactive"] = None
        else:
            # 非业务意图（manual/greeting/unknown），清除追问状态
            updates["interactive"] = None    

        return updates

    # ------------------------------------------------------------------
    # 消息过滤
    # ------------------------------------------------------------------

    async def _filter_message(self, message: str) -> bool:
        """
        过滤用户消息。
        返回 True 表示消息正常，False 表示需要拦截。
        """
        # 简单关键词拦截（成本低）
        block_keywords = ["暴力", "色情", "赌博", "毒品"]
        for kw in block_keywords:
            if kw in message:
                logger.warning(f"消息包含敏感词: {kw}")
                return False

        # 极端情况用 LLM 判断（可配置开关）
        # prompt = f"判断以下消息是否与客服相关，只输出 YES 或 NO: {message}"
        # result = await self.llm.complete(prompt, temperature=0.0)
        # return "YES" in result.upper()

        return True

    # ------------------------------------------------------------------
    # 意图识别
    # ------------------------------------------------------------------

    async def _recognize_intent(self, messages: List[Dict[str, str]]) -> Dict[str, str]:
        """调用 LLM 识别意图和补充状态"""
        system_prompt = self._build_intent_system_prompt()
        history_str = json.dumps(messages, ensure_ascii=False)

        try:
            raw_response = await self.llm.complete(
                history_str,
                system_prompt=system_prompt,
                temperature=0.3,
            )
            logger.info(f"LLM 原始响应: {raw_response}")

            # 提取 JSON
            result = self._extract_json(raw_response)
            logger.info(f"解析结果: {result}")

            return {
                "intent": result.get("intent", "unknown"),
                "supplement": result.get("supplement", "none"),
            }
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return {"intent": "manual", "supplement": "none"}

    def _build_intent_system_prompt(self) -> str:
        """构造意图识别的 System Prompt"""
        # 从配置读取意图列表
        intent_items = []
        for intent_id, intent_name in self.intent_registry.list_names().items():
            intent_items.append(f"- {intent_id}: {intent_name}")

        intent_list = "\n".join(intent_items)

        return f"""你是对话意图分析专家。分析用户输入的对话历史，输出用户当前意图和补充状态。
        ## 意图类型
        {intent_list}
        - greeting: 用户只是打招呼、问好、寒暄（如"你好"、"在吗"、"早上好"、"嗨"）
        - off_topic: 用户输入与客服业务完全无关的内容。包括：闲聊（如"今天天气不错"）、纯名词（如"霓虹"、"苹果"、"篮球"，没有提出具体客服问题）、无意义重复字符/乱码（如"卡卡卡卡卡"、"吭吭唧唧咔咔咔"）、诗词、娱乐八卦、时事新闻等
        - manual: 用户明确要求转人工客服或情绪很不满（如"人工客服"、"转人工"、"我要投诉"）
        - unknown: 用户输入模糊，但可能与客服相关，只是无法确定具体类别（如"怎么办"、"出问题了"）

        ## 补充状态（三选一）
        - none: 机器人未追问，或用户刚切换意图
        - ing: 机器人正在追问，用户正在补充信息中
        - done: 用户已明确表示补充完毕或不继续回答（说"没有"/"没了"/"取消"/"算了"/"不要了"/"不用了"/"跳过"/"不知道"/"没有呢"/"没"）

        ## 核心规则
        1. 意图切换时，supplement 必须为 none
        2. 只有机器人追问后，用户才可能处于 ing 或 done
        3. 用户说"没有"/"没了"/"取消"/"算了"/"不要了"/"不用了"/"跳过"/"不知道"/"没有呢"/"没"时，supplement = done
        4. 当用户表达不满、愤怒、情绪化时，intent = "manual"
        5. 用户只是打招呼（"你好"、"在吗"）时，intent = "greeting"
        6. 用户输入与客服完全无关时，intent = "off_topic"
        7. 用户输入明显无意义的重复字符、乱码（如"卡卡卡卡卡"、"吭吭唧唧咔咔咔"）时，intent = "off_topic"
        8. 用户输入模糊、无法判断时，intent = "unknown"

        ## 分析步骤
        1. 提取最后一条用户消息，判断意图
        2. 对比上一轮意图，判断是否切换
        3. 检查最后一条机器人消息是否包含追问词（请补充、请提供、还有吗）
        4. 若意图切换 → {{"intent": "xxx", "supplement": "none"}}
        5. 若未切换且机器人追问 →
        - 用户消息含"没有"/"没了"/"取消"/"算了"/"不要了"/"不用了"/"跳过"/"不知道"/"没有呢"/"没" → done
        - 否则 → ing

        ## 输出格式
        只输出 JSON，不要其他内容：
        {{"intent": "xxx", "supplement": "xxx"}}

        ## 示例
        输入：[{{"role":"user","content":"系统报错怎么办？"}}]
        输出：{{"intent":"technical","supplement":"none"}}

        输入：[{{"role":"user","content":"你好"}}]
        输出：{{"intent":"greeting","supplement":"none"}}

        输入：[{{"role":"user","content":"今天天气不错"}}]
        输出：{{"intent":"off_topic","supplement":"none"}}

        输入：[{{"role":"user","content":"霓虹"}}]
        输出：{{"intent":"off_topic","supplement":"none"}}

        输入：[{{"role":"user","content":"周杰伦的歌"}}]
        输出：{{"intent":"off_topic","supplement":"none"}}

        输入：[{{"role":"user","content":"吭吭唧唧咔咔咔"}}]
        输出：{{"intent":"off_topic","supplement":"none"}}

        输入：[{{"role":"assistant","content":"请提供错误代码"}},{{"role":"user","content":"500"}}]
        输出：{{"intent":"technical","supplement":"ing"}}

        输入：[{{"role":"assistant","content":"请提供错误代码"}},{{"role":"user","content":"没有"}}]
        输出：{{"intent":"technical","supplement":"done"}}"""

    def _is_obviously_off_topic(self, text: str) -> bool:
        """
        简单启发式判断：输入是否明显与客服业务无关。
        用于兜底 LLM 未识别出的 off_topic 情况。
        """
        lowered = text.lower().strip()
        # 太短（<=4 字）且不含业务关键词
        business_kw = ["报错", "错误", "系统", "账号", "密码", "登录", "注册", "充值", "套餐", "升级", "问题", "帮助", "客服", "人工", "投诉", "功能", "使用", "怎么", "如何", "为什么", "怎么办", "咨询"]
        if len(text) <= 4 and not any(kw in lowered for kw in business_kw):
            return True
        # 明显的闲聊/无关关键词
        off_topic_kw = ["天气", "新闻", "股票", "彩票", "娱乐", "明星", "电影", "电视剧", "游戏", "吃饭", "好吃", "好玩", "好看", "好听", "诗词", "歌词", "八卦"]
        if any(kw in lowered for kw in off_topic_kw):
            return True
        # 无意义重复字符/乱码检测
        if self._is_gibberish(text):
            return True
        return False

    def _is_gibberish(self, text: str) -> bool:
        """判断输入是否为明显无意义的乱码/重复字符"""
        if len(text) < 8:
            return False
        # 去重字符占比过低（重复率极高）
        unique_ratio = len(set(text)) / len(text)
        if unique_ratio < 0.35:  # 重复率超过 65%
            return True
        # 连续短模式重复（如"科技科技科技"、"卡卡卡卡"）
        for length in range(2, min(6, len(text) // 2 + 1)):
            for i in range(len(text) - length + 1):
                pattern = text[i:i + length]
                count = text.count(pattern)
                if count >= 4 and count * length / len(text) > 0.4:
                    return True
        return False

    def _extract_json(self, raw: str) -> Dict[str, Any]:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        # 尝试从代码块中提取
        import re
        json_match = re.search(r'\{[\s\S]*?\}', raw)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # 兜底：返回默认值
        return {"intent": "unknown", "supplement": "none"}

    # ------------------------------------------------------------------
    # 收集信息处理
    # ------------------------------------------------------------------

    def _handle_collected_info(
        self,
        state: ITRState,
        intent: str,
        supplement: str,
        last_msg: str,
    ) -> Dict[str, Any]:
        """
        处理 collected_info 的初始化和更新。
        返回需要更新的 State 字段。
        """
        prev_intent = state.get("intent")
        prev_supplement = state.get("supplement", "none")
        is_new_topic = (prev_intent != intent) and (prev_intent is not None)

        # 获取意图配置
        intent_config = self.intent_registry.get(intent)
        if not intent_config:
            return {}

        updates: Dict[str, Any] = {}

        if is_new_topic:
            # 意图切换，重置所有状态
            logger.info(f"意图变化: {prev_intent} -> {intent}，重置收集状态")
            collected = {}
            updates["info_collection_round"] = 0
            updates["info_complete"] = False
            updates["retry_count"] = 0
            updates["solution_confidence"] = 0.0
        else:
            # 同一意图，保留已有数据
            collected = dict(state.get("collected_info", {}))

        # 初始化所有字段为 None
        all_fields = intent_config.get_all_fields()
        for field in all_fields:
            if field.id not in collected:
                collected[field.id] = None

        # 如果是第一轮（supplement=none），尝试提取开放文本字段
        if supplement == "none" and len(state.get("messages", [])) <= 2:
            extracted = self._extract_open_text_fields(last_msg, intent_config)
            for field_id, value in extracted.items():
                if field_id in collected and collected[field_id] is None:
                    collected[field_id] = value
                    logger.info(f"开放文本提取: {field_id} = {value[:50] if value else 'None'}...")

        # 如果 supplement=done，标记信息完整
        if supplement == "done":
            # 将剩余的 None 字段填为"用户未提供"
            for field in all_fields:
                if collected.get(field.id) is None:
                    collected[field.id] = "用户未提供"
            updates["info_complete"] = True
            logger.info("用户表示补充完毕，标记信息完整")

        updates["collected_info"] = collected
        logger.info(f"当前 collected_info: {collected}")

        return updates

    def _extract_open_text_fields(self, user_msg: str, intent_config) -> Dict[str, str]:
        """
        从用户第一轮消息中提取开放文本字段（A类）。
        这里用简单关键词匹配，后续可升级为 LLM 提取。
        """
        extracted: Dict[str, str] = {}
        lowered = user_msg.lower()

        for field in intent_config.open_text_fields:
            # 简单提取：取用户消息中可能相关的部分
            # MVP 阶段简化处理，直接存入完整消息
            # 后续可用 LLM 精确提取
            extracted[field.id] = user_msg

        return extracted

    # ------------------------------------------------------------------
    # 追问指令生成（原 info_collection 逻辑）
    # ------------------------------------------------------------------

    def _build_interactive(self, collected: Dict[str, Any], intent: str) -> Optional[Dict[str, Any]]:
        """
        检查缺失字段，生成追问指令。
        返回 interactive 字典，或 None（字段已齐全）。
        """
        intent_config = self.intent_registry.get(intent)
        if not intent_config:
            return None

        # 找到第一个缺失的必填字段
        missing = None
        for field in intent_config.get_all_fields():
            if field.required and collected.get(field.id) is None:
                missing = field
                break

        if not missing:
            return None

        # 根据字段类型生成不同的追问指令
        if isinstance(missing, EnumField):
            # B类：选项卡片
            return {
                "type": "ask_options",
                "field_id": missing.id,
                "field_label": missing.label,
                "question": f"为了更好地帮助您，请问您的{missing.label}是什么？",
                "options": [
                    {"value": opt.value, "label": opt.label}
                    for opt in missing.options
                ],
            }

        elif isinstance(missing, RuleField):
            # C类：规则输入
            return {
                "type": "ask_input",
                "field_id": missing.id,
                "field_label": missing.label,
                "question": f"为了更好地帮助您，请问您的{missing.label}是什么？",
                "placeholder": f"例如：{missing.example}",
                "example": missing.example,
                "hint": missing.error_message,
            }

        elif isinstance(missing, OpenTextField):
            # A类：开放文本（追问场景）
            return {
                "type": "ask_input",
                "field_id": missing.id,
                "field_label": missing.label,
                "question": f"为了更好地帮助您，请问{missing.label}是什么？",
                "placeholder": f"请详细描述{missing.label}",
                "example": "请尽量详细描述",
                "hint": missing.extraction_prompt,
            }

        return None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _get_last_user_message(self, messages: List[Dict[str, Any]]) -> str:
        """获取最后一条用户消息"""
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""


def _append_assistant(messages: List[Dict[str, Any]], content: str) -> List[Dict[str, Any]]:
    """在消息列表末尾追加助手回复"""
    result = list(messages)
    result.append({"role": "assistant", "content": content})
    return result
