"""
场景测试脚本 —— 验证追问、转人工、排队等关键状态转换逻辑。

不依赖 LLM，只验证 _dispatch_message 中的条件分支和状态转换。
用法: cd tests && python scenario_test.py
"""

import sys
import os

# 把 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ------------------------------------------------------------------
# 模拟 app.py 中的辅助函数（直接复制过来验证）
# ------------------------------------------------------------------
def _is_manual_request(text: str) -> bool:
    keywords = ["人工", "客服", "转人工", "人工客服", "找人工", "接人工", "投诉", "我要投诉", "找你们领导"]
    return any(kw in text.lower() for kw in keywords)


def _is_cancel_or_done(text: str) -> bool:
    keywords = ["取消", "算了", "不要了", "不用了", "跳过", "没有", "没了", "没有了", "不填了", "不知道"]
    return any(kw in text.lower() for kw in keywords)


def _is_strong_cancel(text: str) -> bool:
    strong_keywords = ["没有", "没了", "没有了", "不知道", "不填了", "不想填", "跳过"]
    return any(kw in text.lower() for kw in strong_keywords)


def _is_cancel_manual_request(text: str) -> bool:
    keywords = ["取消", "算了", "不排队了", "取消人工", "取消排队", "不等了"]
    return any(kw in text.lower() for kw in keywords)


def _looks_like_new_intent(text: str) -> bool:
    question_marks = ["?", "？", "怎么", "怎么办", "如何", "为什么", "请问", "怎样"]
    if any(q in text for q in question_marks):
        return True
    if len(text) > 15:
        return True
    intent_keywords = ["报错", "错误", "系统", "功能", "使用", "咨询", "问题", "帮助", "升级", "套餐", "账号", "密码", "登录", "注册", "忘记密码", "修改", "绑定", "解绑"]
    if any(kw in text for kw in intent_keywords):
        return True
    off_topic_keywords = ["天气", "时间", "新闻", "股票", "彩票", "娱乐", "明星", "电影", "游戏", "吃饭", "好吃", "好玩"]
    if any(kw in text for kw in off_topic_keywords):
        return True
    return False


# ------------------------------------------------------------------
# 模拟路由逻辑（从 graph_builder._route_intent 复制）
# ------------------------------------------------------------------
def route_intent(state: dict) -> str:
    intent = state.get("intent")
    status = state.get("status")

    if status in ("transferred", "manual_queue"):
        return "END_排队中"
    if intent == "off_topic":
        return "END"
    if intent == "manual":
        return "session_end"
    if state.get("interactive"):
        return "END_追问中"
    if state.get("info_complete"):
        return "solution_generation"
    if intent:
        return "solution_generation"
    return "solution_generation"


# ------------------------------------------------------------------
# 模拟 _dispatch_message 的核心分支逻辑
# ------------------------------------------------------------------
def dispatch_logic(state: dict, msg: dict) -> dict:
    """
    返回处理结果：
      action: "skip" | "field_fill" | "cancel_manual" | "satisfaction" | "choice" | "rule_validation" | "normal_flow"
      description: 文字说明
      new_state: 修改后的 state（部分字段）
    """
    msg_type = msg.get("type", "text")
    user_content = msg.get("content", "")
    interactive = state.get("interactive")
    status = state.get("status")

    # 优先级-1：人工排队状态
    if status in ("transferred", "manual_queue"):
        if _is_cancel_manual_request(user_content) or msg_type == "cancel_manual":
            return {"action": "cancel_manual", "description": "取消人工排队", "new_state": {"status": "active", "interactive": None, "intent": None, "info_complete": False}}
        return {"action": "queue_reply", "description": "提示正在排队", "new_state": {}}

    # 优先级0：追问状态下的特殊输入
    if interactive and msg_type == "text":
        interactive_type = interactive.get("type")

        if _is_manual_request(user_content):
            return {"action": "normal_flow", "description": "追问状态下转人工，清除追问", "new_state": {"interactive": None}}

        should_skip = False
        if interactive_type == "ask_options":
            should_skip = _is_cancel_or_done(user_content)
        elif interactive_type == "ask_input":
            should_skip = _is_strong_cancel(user_content)

        if should_skip:
            return {"action": "skip", "description": "用户跳过追问，标记完成", "new_state": {"interactive": None, "info_complete": True}}

        if _looks_like_new_intent(user_content):
            return {"action": "normal_flow", "description": "追问状态下新意图，清除追问", "new_state": {"interactive": None}}

    # 优先级1：field_fill
    if msg_type == "field_fill":
        return {"action": "field_fill", "description": "用户点击选项卡片", "new_state": {}}

    # 优先级2：cancel_manual
    if msg_type == "cancel_manual":
        return {"action": "cancel_manual", "description": "取消人工排队", "new_state": {"status": "active", "interactive": None, "intent": None, "info_complete": False}}

    # 优先级3：satisfaction / choice
    if msg_type == "satisfaction" or status == "awaiting_satisfaction":
        return {"action": "satisfaction", "description": "处理满意度", "new_state": {}}
    if msg_type == "choice" or status == "awaiting_choice":
        return {"action": "choice", "description": "处理选择", "new_state": {}}

    # 优先级4：规则字段验证
    if interactive and msg_type == "text":
        field_id = msg.get("field_id") or interactive.get("field_id")
        # 简化：假设当前追问的是规则字段（C类）
        if interactive_type == "ask_input":
            # 如果用户输入不是 manual/cancel/new_intent，走规则验证
            # 这里简化，假设会验证
            return {"action": "rule_validation", "description": "规则字段验证", "new_state": {}}

    # 优先级5：normal flow
    return {"action": "normal_flow", "description": "正常对话流程", "new_state": {}}


# ------------------------------------------------------------------
# 测试用例
# ------------------------------------------------------------------
def test_case(name: str, state: dict, msg: dict, expected_action: str, expected_desc_contains: str = None) -> bool:
    result = dispatch_logic(state, msg)
    ok = result["action"] == expected_action
    if expected_desc_contains:
        ok = ok and expected_desc_contains in result["description"]
    status = "[PASS]" if ok else "[FAIL]"
    if not ok:
        print(f"  {status} | {name}")
        print(f"    期望: {expected_action}, 实际: {result['action']} | {result['description']}")
    else:
        print(f"  {status} | {name} → {result['description']}")
    return ok


def run_all_tests():
    passed = 0
    failed = 0

    print("\n" + "=" * 70)
    print("[场景测试] 追问 / 转人工 / 排队 状态转换")
    print("=" * 70)

    # --------------------------------------------------------------
    # 场景组1：选项卡片追问（B类字段）
    # --------------------------------------------------------------
    print("\n[场景组1] 选项卡片追问（ask_options）")
    state_options = {
        "status": "active",
        "intent": "account",
        "interactive": {"type": "ask_options", "field_id": "account_type", "question": "请选择账号类型"},
    }

    if test_case("输入'转人工'", state_options.copy(), {"type": "text", "content": "转人工"}, "normal_flow", "转人工"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'人工'", state_options.copy(), {"type": "text", "content": "人工"}, "normal_flow", "转人工"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'取消'", state_options.copy(), {"type": "text", "content": "取消"}, "skip"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'算了'", state_options.copy(), {"type": "text", "content": "算了"}, "skip"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'没有'", state_options.copy(), {"type": "text", "content": "没有"}, "skip"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'系统报错怎么办'", state_options.copy(), {"type": "text", "content": "系统报错怎么办"}, "normal_flow", "新意图"):
        passed += 1
    else:
        failed += 1

    # --------------------------------------------------------------
    # 场景组2：规则字段追问（C类字段）
    # --------------------------------------------------------------
    print("\n[场景组2] 规则字段追问（ask_input - 手机号）")
    state_rule = {
        "status": "active",
        "intent": "account",
        "interactive": {"type": "ask_input", "field_id": "phone", "question": "请输入手机号"},
    }

    if test_case("输入'转人工'", state_rule.copy(), {"type": "text", "content": "转人工"}, "normal_flow", "转人工"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'算了'（不应跳过，应走格式验证）", state_rule.copy(), {"type": "text", "content": "算了"}, "rule_validation"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'取消'（不应跳过，应走格式验证）", state_rule.copy(), {"type": "text", "content": "取消"}, "rule_validation"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'没有'（明确否定，允许跳过）", state_rule.copy(), {"type": "text", "content": "没有"}, "skip"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'不知道'（明确否定，允许跳过）", state_rule.copy(), {"type": "text", "content": "不知道"}, "skip"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'系统报错怎么办'（新意图）", state_rule.copy(), {"type": "text", "content": "系统报错怎么办"}, "normal_flow", "新意图"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'功能咨询'（新意图）", state_rule.copy(), {"type": "text", "content": "功能咨询"}, "normal_flow", "新意图"):
        passed += 1
    else:
        failed += 1

    if test_case("输入'天气好'（新意图）", state_rule.copy(), {"type": "text", "content": "天气好"}, "normal_flow"):
        passed += 1
    else:
        failed += 1

    # --------------------------------------------------------------
    # 场景组3：人工排队状态
    # --------------------------------------------------------------
    print("\n[场景组3] 人工排队状态")
    state_queue = {
        "status": "transferred",
        "intent": "manual",
        "interactive": None,
    }

    if test_case("排队中输入'账号问题'", state_queue.copy(), {"type": "text", "content": "账号问题"}, "queue_reply"):
        passed += 1
    else:
        failed += 1

    if test_case("排队中输入'取消人工'", state_queue.copy(), {"type": "text", "content": "取消人工"}, "cancel_manual"):
        passed += 1
    else:
        failed += 1

    if test_case("排队中输入'取消排队'", state_queue.copy(), {"type": "text", "content": "取消排队"}, "cancel_manual"):
        passed += 1
    else:
        failed += 1

    if test_case("排队中输入'算了'", state_queue.copy(), {"type": "text", "content": "算了"}, "cancel_manual"):
        passed += 1
    else:
        failed += 1

    # --------------------------------------------------------------
    # 场景组4：路由逻辑
    # --------------------------------------------------------------
    print("\n[场景组4] 路由逻辑（_route_intent）")

    def test_route(name: str, state: dict, expected: str) -> bool:
        result = route_intent(state)
        ok = result == expected
        status = "[PASS]" if ok else "[FAIL]"
        if not ok:
            print(f"  {status} | {name} → 期望: {expected}, 实际: {result}")
        else:
            print(f"  {status} | {name} → {result}")
        return ok

    if test_route("manual 意图", {"intent": "manual", "interactive": None}, "session_end"):
        passed += 1
    else:
        failed += 1

    if test_route("off_topic 意图", {"intent": "off_topic", "interactive": None}, "END"):
        passed += 1
    else:
        failed += 1

    if test_route("排队中(manual_queue)", {"intent": "account", "status": "manual_queue", "interactive": None}, "END_排队中"):
        passed += 1
    else:
        failed += 1

    if test_route("排队中(transferred)", {"intent": "account", "status": "transferred", "interactive": None}, "END_排队中"):
        passed += 1
    else:
        failed += 1

    if test_route("有追问", {"intent": "account", "interactive": {"type": "ask_options"}}, "END_追问中"):
        passed += 1
    else:
        failed += 1

    if test_route("信息完整", {"intent": "account", "interactive": None, "info_complete": True}, "solution_generation"):
        passed += 1
    else:
        failed += 1

    if test_route("正常业务意图", {"intent": "technical", "interactive": None}, "solution_generation"):
        passed += 1
    else:
        failed += 1

    # --------------------------------------------------------------
    # 场景组5：辅助函数
    # --------------------------------------------------------------
    print("\n[场景组5] 辅助函数")

    def test_func(name: str, result: bool, expected: bool) -> bool:
        ok = result == expected
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status} | {name} → {result}")
        return ok

    if test_func("_is_manual_request('转人工')", _is_manual_request("转人工"), True):
        passed += 1
    else:
        failed += 1

    if test_func("_is_manual_request('人工')", _is_manual_request("人工"), True):
        passed += 1
    else:
        failed += 1

    if test_func("_is_strong_cancel('没有')", _is_strong_cancel("没有"), True):
        passed += 1
    else:
        failed += 1

    if test_func("_is_strong_cancel('算了')", _is_strong_cancel("算了"), False):
        passed += 1
    else:
        failed += 1

    if test_func("_is_strong_cancel('取消')", _is_strong_cancel("取消"), False):
        passed += 1
    else:
        failed += 1

    if test_func("_is_cancel_manual_request('取消人工')", _is_cancel_manual_request("取消人工"), True):
        passed += 1
    else:
        failed += 1

    if test_func("_looks_like_new_intent('系统报错怎么办')", _looks_like_new_intent("系统报错怎么办"), True):
        passed += 1
    else:
        failed += 1

    # --------------------------------------------------------------
    # 汇总
    # --------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 70 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
