# ITR 智能客服机器人

> 一个**配置驱动**、**LangGraph 编排**的智能客服机器人 MVP。新增业务线 = 新增 YAML 配置，零代码改动。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---
## 预览
![1](/public/1.png)![2](/public/2.png)
![3](/public/3.png)![4](/public/4.png)

---

## 目录

- [快速开始](#快速开始)
- [功能特性](#功能特性)
- [架构设计](#架构设计)
- [核心设计：字段三分法](#核心设计字段三分法)
- [完整对话流程](#完整对话流程)
- [前后端消息协议](#前后端消息协议)
- [State 设计规范](#state-设计规范)
- [MemorySaver 与 Checkpoint](#memorysaver-与-checkpoint)
- [目录结构](#目录结构)
- [编码规范](#编码规范)
- [扩展指南](#扩展指南)
- [异常处理与常见陷阱](#异常处理与常见陷阱)
- [术语表](#术语表)

---

## 快速开始

### 1. 安装依赖

```bash
cd my-itr-mvp
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写你的 API Key 和服务地址
```

### 3. 启动服务

```bash
cd src
python app.py
```

访问 http://localhost:8000 查看前端页面。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **配置驱动** | 业务数据（意图、字段、话术）外置到 YAML，新增业务线 = 新增配置 |
| **字段三分法** | A类（开放文本提取）+ B类（选项卡片）+ C类（规则格式验证） |
| **智能追问** | 意图识别后自动检查缺失字段，逐轮追问，支持跳过 |
| **转人工兜底** | 格式验证失败 5 次自动转人工，排队状态下输入新问题自动取消 |
| **无关内容拦截** | off_topic / 乱码 / 无意义重复字符自动拦截，不调用大模型 |
| **意图切换检测** | 追问状态下支持转人工、取消追问、切换新意图 |
| **LangGraph 编排** | 保留 Checkpoint、Reducer 机制，多轮对话状态连续 |

---

## 架构设计

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  表现层 (Presentation)                                       │
│  FastAPI + WebSocket │ 前端聊天页面 │ 会话生命周期管理        │
├─────────────────────────────────────────────────────────────┤
│  编排层 (Orchestration) —— LangGraph                         │
│  声明式工作流 │ 条件路由 │ State 合并 │ Checkpoint 管理         │
├─────────────────────────────────────────────────────────────┤
│  领域层 (Domain) —— 纯接口 + 纯数据结构                        │
│  ITRState │ INode │ IntentRegistry │ SkillRegistry             │
├─────────────────────────────────────────────────────────────┤
│  应用层 (Application) —— 业务实现                             │
│  IntentRecognitionNode │ SolutionGenerationNode │ SessionEndNode │
├─────────────────────────────────────────────────────────────┤
│  基础设施层 (Infrastructure)                                  │
│  LLMSkill │ RAGSkill │ DBSkill                               │
├─────────────────────────────────────────────────────────────┤
│  配置层 (Configuration) —— 驱动所有行为                        │
│  config/intents/*.yaml │ config/settings.py                    │
└─────────────────────────────────────────────────────────────┘
```

### 核心原则

> **配置即代码，但配置不等于代码。**  
> 代码只保留"如何执行"的机制，不保留"执行什么"的数据。

### 路由设计

Node 只负责 `execute()`，不碰路由逻辑。路由集中到 `core/graph_builder.py`：

```
intent_recognition 执行
    │
    ├── intent=manual ───────→ session_end ──→ END
    │
    ├── intent=off_topic ────→ 直接拦截回复 ──→ END
    │
    ├── interactive 存在 ────→ 追问卡片/输入框 ──→ END
    │
    ├── info_complete=True ──→ solution_generation ──→ END
    │
    └── 其他业务意图 ─────────→ solution_generation ──→ END
```

---

## 业务场景-待优化
### 用户意图识别系统
1. “双核”引擎
同时“填槽”和“识别意图变更”，两个关键核心模块：
（1）对话状态跟踪（DST）模块：这个模块是系统的短期记忆，负责记住“我们在哪了”。例如，它知道当前正在收集“手机号”这个信息，并知道已经问了第几次。
（2）全局意图识别模块：这个模块是系统的“雷达”，它以高于当前任务的优先级，持续扫描用户的每一句话。它的职责是判断用户是不是想“切换话题”、“取消操作”或“转人工”。

2. 优先级决策机制
当用户输入时，系统会先走判断逻辑，而不是直接将其当作“手机号”来处理：
（1）优先级1：处理高权限全局指令，用户消息首先会经过一个“快速通道”，识别是否存在强制跳转指令。如：
转人工：用户一旦说“转人工”、“找真人客服”，系统应立即处理，而不是继续追问手机号。
取消/退出：用户说“算了”、“不办了”，系统应礼貌结束当前流程，而不是追问信息。
明确的新意图：用户说“我想查物流”，系统应立即跳出当前流程，响应用户新需求。

（2）优先级2：判断是否与当前任务相关：如果没有高权限指令，系统会判断用户回答是否与当前任务有关。
例如，机器人问“请输入您的手机号”，用户回答是“138****0000”。这明显是任务相关信息，只做格式校验，不判断意图变更。
如果用户回答是“我的订单丢了怎么办？”，这个回答与“提供手机号”的任务相关性极低。此时，哪怕格式不对，系统也不会再提示“请输入11位手机号”，而是将其识别为新意图，进行跳转或兜底回答。

（3）优先级3：常规槽位校验：只有当用户输入被判定为与当前任务相关（或未触发新意图）时，才进入常规的校验流程。如果格式错误，就友好地提示用户重新输入。

示例实现逻辑：

```code
用户输入
    ↓
第一层：规则层（格式校验、关键词白名单/黑名单）
    ↓
第二层：大模型层（语义相似度、意图分类、相关性判断）
    ↓
第三层：决策层（基于置信度做阈值判断）
```

```python
# 伪代码示例：在追问运单号的场景下的决策逻辑

def on_user_message(user_input, current_state):
    # 1. 最高优先级：执行全局意图识别
    # 这里会调用一个独立的、经过训练的意图识别模型
    global_intent = global_intent_classifier(user_input) 
    
    if global_intent == "TRANSFER_TO_HUMAN":
        return transfer_to_human_agent()
    elif global_intent == "CANCEL":
        return say_goodbye_and_reset()
    elif global_intent == "CHECK_REFUND_STATUS":
        # 用户跳转到了新意图，中断当前流程，开始处理退款
        return start_refund_workflow() 
    
    # 2. 如果用户没有触发跳转，再判断是否与当前任务（收集运单号）相关
    # 计算用户输入与“运单号”这个语义槽位的匹配度
    relevance_score = calculate_relevance(user_input, current_state.slot_name)
    
    if relevance_score < LOW_RELEVANCE_THRESHOLD:
        # 用户说的是其他事情（如“再推荐个别的商品”），但又不是明确指令
        # 此时跳出，并给出“全局回复”，将对话拉回原任务
        return give_global_answer_and_restore_task(user_input)
    
    # 3. 最后，才进入当前任务的流程
    if is_valid_tracking_number(user_input):
        return continue_to_next_step()
    else:
        return ask_for_tracking_number_again()
```

追问与回答的相关性设计：
方案一：大模型
```code
def get_relevance_by_llm(user_input, slot_name, slot_example):
    prompt = f"""
你是智能客服的决策模块。当前系统正在向用户追问：{slot_name}（例如：{slot_example}）

用户最新回复："{user_input}"

请判断用户回复是否与【提供{slot_name}】这个任务相关。
只输出0-1之间的数字，不要有任何解释：
- 0.9-1.0: 明显相关，用户在提供所问信息
- 0.6-0.8: 可能相关，需要进一步确认  
- 0.3-0.5: 不太相关，用户似乎换了话题
- 0.0-0.2: 完全不相关，明确的新意图

输出格式：{"relevance_score": 0.xx}
"""
    response = call_llm(prompt)
    return response.relevance_score
```

方案二：关键词加权 + 规则兜底（无大模型时的降级方案）
def compute_relevance_fallback(user_input, slot_keywords, slot_type):
    score = 0.0
    
    # 1. 格式匹配加分（高权重）
    if slot_type == "phone" and re.match(r'1[3-9]\d{9}', user_input):
        score += 0.6
    elif slot_type == "tracking_number" and re.match(r'[A-Z0-9]{10,}', user_input):
        score += 0.6
    
    # 2. 关键词匹配加分（中权重）
    for kw in slot_keywords:  # 如 ["手机", "号码", "电话"]
        if kw in user_input:
            score += 0.15
    
    # 3. 否定词减分
    if any(word in user_input for word in ["不是", "不想", "算了", "取消"]):
        score -= 0.3
    
    # 归一化到[0,1]
    return min(1.0, max(0.0, score))
---

## 核心设计：字段三分法

所有需要收集的信息，按交互方式分为三类：

| 类型 | 名称 | 交互方式 | 前端展示 | 后端处理 |
|------|------|---------|---------|---------|
| **A类** | 开放文本 | 第一轮由 LLM 从用户原始消息提取 | 无需追问 | LLM 提取 |
| **B类** | 枚举选项 | 前端显示选项卡片，用户点击选择 | 卡片/按钮组 | 直接写入 |
| **C类** | 规则格式 | 前端显示提示+格式样例，用户聊天框输入 | 消息气泡+样例标签 | 正则提取，失败重试 |

### YAML 配置示例

```yaml
id: technical
name: 技术支持

# A类：开放文本（第一轮 LLM 提取）
open_text_fields:
  - id: error_hint
    label: 问题描述
    extraction_prompt: "用户描述的问题是什么？"

# B类：枚举选项（前端卡片）
enum_fields:
  - id: product_module
    label: 产品模块
    required: true
    options:
      - value: order
        label: 📦 订单模块
      - value: user
        label: 👤 用户中心

# C类：规则格式（正则提取）
rule_fields:
  - id: phone
    label: 手机号
    required: true
    type: regex
    pattern: '1[3-9]\d{9}'
    example: "13800138000"
    error_message: "请输入正确的11位手机号"
```

---

## 完整对话流程

### 第一轮：用户提问

```
用户输入: "我的系统报错了，点击查询按钮就提示500错误"
    │
    ▼
intent_recognition Node
├── 识别意图 → technical
├── 提取开放文本（A类）
│   └── error_hint: "点击查询按钮就提示500错误"
└── 初始化 B类/C类字段为 None
    │
    ▼
检查缺失字段：
  - B类: product_module ❌ 缺失
  - C类: phone ❌ 缺失
    │
    ▼
发送追问指令给前端：
  → ask_options (product_module)
    │
    ▼
本轮结束（END）
```

### 第二轮：用户交互

**场景A：用户点击选项卡片**
```
用户点击 "📦 订单模块"
    │
    ▼
前端发送: {"type": "field_fill", "field_id": "product_module", "value": "order"}
    │
    ▼
后端直接写入 collected_info.product_module = "order"
    │
    ▼
检查还有缺失字段：phone ❌
    │
    ▼
继续追问：ask_input (phone) + 格式样例
```

**场景B：用户输入规则字段**
```
用户输入: "13800138000"
    │
    ▼
后端正则匹配 → 成功 ✅ → phone = "13800138000"
    │
    ▼
检查还有缺失字段：✅ 全部完成
    │
    ▼
路由到 solution_generation → 生成回复
```

**场景C：用户输入格式错误**
```
用户输入: "abc"
    │
    ▼
后端正则匹配 → 失败 ❌
    │
    ▼
后端回复前端：
  "您输入的格式不对，无法识别，请重新按照样例格式输入。"
  "💡 格式样例：13800138000"
    │
    ▼
计数器 +1（失败次数 = 1）
    │
    ▼
本轮结束，等待用户重新输入
```

**场景D：追问状态下用户输入"转人工"**
```
用户输入: "转人工"
    │
    ▼
_dispatch_message 检测：追问状态下收到转人工请求
    │
    ▼
清除追问状态，走 normal flow
    │
    ▼
LLM 识别 intent=manual
    │
    ▼
session_end 返回："已为您转接人工客服，请稍等，正在为您排队..."
    │
    ▼
状态变为 manual_queue
```

**场景E：追问状态下用户输入"算了"**
```
用户输入: "算了"
    │
    ▼
选项卡片追问：_is_cancel_or_done("算了") → True → 跳过追问
    │
    ▼
规则字段追问：_is_strong_cancel("算了") → False → 走格式验证
    │
    ▼
（规则字段场景下，"算了"会被当作格式错误处理）
```

**场景F：追问状态下用户输入新问题**
```
用户输入: "系统报错怎么办"
    │
    ▼
_dispatch_message 检测：追问状态下收到新意图输入
    │
    ▼
清除追问状态，走 normal flow
    │
    ▼
LLM 重新识别意图
```

### 正则失败次数处理策略

| 失败次数 | 处理方式 | 前端展示 |
|---------|---------|---------|
| 1-2次 | "格式不对，请按样例重新输入" | 红色错误提示 + 样例 |
| 3次 | "格式不对，请重新输入，或选择转接人工客服" | 错误提示 + "转接人工客服"按钮 |
| 4-5次 | 同上，持续提醒 | 同上 |
| **超过5次** | **强行转接人工服务** | 人工排队状态 + "取消排队"文字链接 |

### 人工排队状态

```
超过5次正则失败 / 用户主动说"转人工"
    │
    ▼
进入人工排队状态（status=manual_queue）
├── 前端显示："已为您转接人工客服，正在排队中..."
├── 显示 "取消排队" 文字链接（点击发送 cancel_manual）
├── 用户输入非取消内容 → 自动取消排队 + 处理新输入
└── 用户输入 "取消"/"算了"/"取消人工" → 取消排队，回到正常对话
```

---

## 前后端消息协议

### 后端 → 前端

| type | 说明 | 示例字段 |
|------|------|---------|
| `welcome` | 欢迎语 | `content` |
| `reply` | 普通文本回复 | `content`, `intent`, `status` |
| `manual_queue` | 人工排队状态（带取消链接） | `content`, `status` |
| `ask_options` | 显示选项卡片（B类字段） | `field_id`, `question`, `options` |
| `ask_input` | 显示规则输入提示（C类字段） | `field_id`, `question`, `example` |
| `error_hint` | 格式错误提示 | `content`, `example`, `retry_count` |
| `error_hint_with_manual` | 错误提示 + 转人工按钮 | `content`, `example`, `retry_count` |
| `force_manual` | 强行转人工（全屏卡片） | `content` |
| `status_change` | 状态变更通知 | `status`, `reset` |
| `error` | 系统错误 | `content` |

### 前端 → 后端

| type | 说明 | 示例字段 |
|------|------|---------|
| `text` | 普通文本输入 | `content`, 可选 `field_id` |
| `field_fill` | 点击选项卡片 | `field_id`, `value` |
| `cancel_manual` | 取消人工排队 | - |

---

## State 设计规范

### 核心字段

| 字段 | 类型 | 说明 |
|-----|------|------|
| `messages` | `List[Dict]` | 对话历史，`{"role": "user|assistant", "content": str}` |
| `intent` | `Optional[str]` | 当前意图：technical/account/billing/feature/greeting/off_topic/manual/unknown |
| `supplement` | `Optional[str]` | 补充状态：none / ing / done |
| `collected_info` | `Dict[str, Any]` | 已收集字段（增量合并） |
| `interactive` | `Optional[Dict]` | 追问交互指令（ask_options / ask_input） |
| `info_complete` | `bool` | 信息收集是否完成 |
| `round_count` | `int` | 当前总对话轮数 |
| `retry_count` | `int` | 规则字段验证失败次数 |
| `status` | `str` | 会话状态：active / ended / transferred / manual_queue / awaiting_choice |
| `session_id` | `Optional[str]` | 会话 ID |

### State 与数据库的分工

| 数据类型 | State | 数据库 |
|---------|-------|--------|
| 当前对话历史 | ✅ 必须有 | ✅ 归档保存 |
| 当前意图 | ✅ | ❌ 临时状态 |
| 已收集字段 | ✅ | ✅ 归档 |
| 追问轮数 | ✅ | ❌ 纯临时计数器 |
| 用户画像 | ❌ | ✅ 从用户服务实时查 |
| 满意度评分 | ❌ | ✅ 直接写入业务表 |

---

## MemorySaver 与 Checkpoint

LangGraph 的 `MemorySaver` 在每次 `graph.invoke()` 后保存完整 State 到内存。下次用相同的 `thread_id` 调用时自动恢复。

```python
config = {"configurable": {"thread_id": session_id}}
result = await graph.ainvoke(state, config=config)
```

**thread_id** 是唯一标识：
- 相同 `thread_id` → 共享存档，对话连续
- 不同 `thread_id` → 互相隔离

### 生产替代

| 特性 | MemorySaver | PostgresSaver / RedisSaver |
|-----|-------------|---------------------------|
| 存储位置 | 内存 | PostgreSQL / Redis |
| 服务重启后 | **数据全丢** | 数据保留 |
| 分布式部署 | 不支持 | 支持（共享存储） |
| 适用场景 | 单机 MVP / 本地开发 | 生产环境 |

### 状态合并陷阱

LangGraph 的合并不删除字段。如果 checkpoint 中有旧字段（如 `interactive`），而 Node 返回的 updates 中没有该字段，旧值会保留。这可能导致追问状态残留。

**解决**：Node 返回时，如果不再追问，显式设置 `"interactive": None` 来清除。

---

## 目录结构

```
itr-agent/
├── config/                          # 业务配置
│   ├── intents/
│   │   ├── technical.yaml           # 意图定义
│   │   ├── account.yaml
│   │   ├── billing.yaml
│   │   └── feature.yaml
│   └── settings.py                  # 运行期配置
│
├── src/
│   ├── core/                        # 框架层
│   │   ├── graph_builder.py         # LangGraph 编排器 + 路由
│   │   ├── state.py                 # ITRState + Reducer
│   │   ├── node_interface.py        # INode 抽象接口
│   │   └── skill_registry.py        # Skill 注册与依赖注入
│   │
│   ├── nodes/                       # 业务层
│   │   ├── intent_recognition.py    # 意图识别 + 追问逻辑集成
│   │   ├── solution_generation.py   # 方案生成
│   │   └── session_end.py           # 会话结束 + 人工排队
│   │
│   ├── skills/                      # 工具层
│   │   ├── llm_skill.py             # 统一 LLM（OpenAI 兼容）
│   │   ├── rag_skill.py             # RAG 检索
│   │   └── db_skill.py              # 数据库
│   │
│   ├── static/
│   │   └── index.html               # 前端聊天页面
│   │
│   └── app.py                       # FastAPI + WebSocket 入口
│
├── tests/
│   └── scenario_test.py             # 场景测试脚本
│
├── requirements.txt
└── README.md
```

---

## 编码规范

### Node 层规范

```python
class IntentRecognitionNode(INode):
    """意图识别 Node
    
    职责:
      - 过滤敏感词/无关内容
      - 调用 LLM 识别意图和补充状态
      - 初始化 collected_info，提取开放文本（A类）
      - 检查缺失字段，生成追问指令（B类/C类）
    """
    name = "intent_recognition"
    
    async def execute(self, state: ITRState) -> Dict[str, Any]:
        # 1. 读取输入
        # 2. 构造 Prompt
        # 3. 调用 Skill
        # 4. 解析响应
        # 5. 返回 State 更新片段
        return {"intent": intent, "interactive": interactive}
```

**Node 戒律**：
- ✅ 构造 Prompt、解析响应、业务判断
- ✅ 调用 Skill 获取外部数据
- ❌ 不碰路由逻辑
- ❌ 不直接操作数据库
- ❌ 不直接操作 WebSocket

### Skill 层规范

```python
class LLMSkill(BaseSkill):
    """LLM 通信 Skill —— 只负责发 HTTP 请求，不碰 Prompt 和业务语义"""
    
    async def complete(self, prompt: str, **kwargs) -> str:
        response = await self.client.chat.completions.create(...)
        return response.choices[0].message.content
```

**Skill 戒律**：
- ✅ 封装外部服务调用
- ✅ 处理网络异常、重试
- ✅ 无状态设计
- ❌ 不碰 Prompt 构造
- ❌ 不碰业务语义解析

### Graph 层规范

```python
class GraphBuilder:
    def _route_intent(self, state: ITRState) -> str:
        # 集中路由判断，不碰业务逻辑
        if state.get("intent") == "manual":
            return "session_end"
        if state.get("interactive"):
            return END
        return "solution_generation"
```

**Graph 戒律**：
- ✅ 管理 Node 连接关系
- ✅ 集中路由判断
- ❌ 不碰业务逻辑
- ❌ 不构造 Prompt

---

## 扩展指南

### 新增一个业务线（如"售后服务"）

1. 创建配置文件：`config/intents/aftersales.yaml`
2. 定义 `open_text_fields`、`enum_fields`、`rule_fields`
3. **无需修改任何代码**，重启服务即可

### 新增一个 Node

1. 实现 Node：`src/nodes/satisfaction_survey.py`
   - 继承 `INode`
   - 实现 `execute()`
2. 注册 Node：在 `GraphBuilder.build()` 中添加
3. 配置路由：在对应的 `_route_*` 方法中添加跳转条件

### 新增一个 Skill（如"物流查询"）

1. 实现 Skill：`src/skills/logistics_skill.py`
2. 注入 Node：在 Node `__init__` 中注入
3. 声明依赖：在 Node 的 `required_skills()` 中声明

### 切换 LLM 厂商

1. 修改 `.env` 中的 `LLM_BASE_URL` 和 `LLM_MODEL`
2. **无需修改 Skill 代码**（统一 OpenAI 格式）

---

## 异常处理与常见陷阱

### 异常处理汇总

| 异常场景 | 处理方式 | 前端展示 |
|---------|---------|---------|
| 正则提取失败（1-2次） | 提示格式错误，要求重新输入 | 红色错误提示 + 样例 |
| 正则提取失败（3-5次） | 提示格式错误 + 转人工选项 | 错误提示 + "转接人工客服"按钮 |
| 正则提取失败（>5次） | 强行转接人工 | 人工排队状态 + "取消排队"链接 |
| 追问状态下说"转人工" | 清除追问，识别 manual 意图 | 转人工提示 |
| 追问状态下说"取消/算了" | 选项卡片：跳过；规则字段：格式验证 | 依场景而定 |
| 追问状态下输入新问题 | 清除追问，重新识别意图 | 新意图的追问或回复 |
| 排队状态下输入新问题 | 自动取消排队，处理新输入 | 取消成功 + 新回复 |
| off_topic / 乱码 | 直接拦截，不调用大模型 | "与客服咨询无关，无法处理" |
| LLM 调用失败 | 兜底返回 manual 意图 | "系统处理出错" |

### 常见陷阱

| 陷阱 | 原因 | 解决方案 |
|-----|------|---------|
| `interactive` 残留导致死循环 | LangGraph 合并不删除字段 | Node 返回时显式设置 `interactive: None` |
| checkpoint 覆盖传入的 state | LangGraph 优先读取 checkpoint | 确保传入 state 包含需要覆盖的字段 |
| 服务重启后对话丢失 | MemorySaver 是内存存储 | 生产环境替换为 PostgresSaver |
| thread_id 重复使用 | 不同用户共享 thread_id | 用 session_id / user_id 作为 thread_id |
| Node 直接操作数据库 | 绕过 Skill 层，耦合基础设施 | 所有外部操作必须通过 Skill |
| Prompt 写在 Skill 里 | Skill 混入业务语义，难以替换 | Prompt 必须写在 Node 层 |

---

## 术语表

| 术语 | 说明 |
|-----|------|
| **Node** | LangGraph 流程中的一个执行节点，封装一段业务逻辑 |
| **Skill** | 外部服务适配器，无业务语义，可独立测试和替换 |
| **State** | LangGraph 在一次会话中跨 Node 共享的临时上下文 |
| **Checkpoint** | LangGraph 在每次 super-step 后保存的状态快照 |
| **thread_id** | Checkpoint 的唯一标识，相同 thread_id 共享对话历史 |
| **MemorySaver** | LangGraph 内置的内存 Checkpoint 持久化器 |
| **Reducer** | LangGraph 的字段级状态合并策略 |
| **Intent** | 用户咨询的意图类别（如 technical/account） |
| **A类字段** | 开放文本字段，第一轮由 LLM 提取 |
| **B类字段** | 枚举字段，前端显示选项卡片 |
| **C类字段** | 规则字段，后端正则验证 |
| **interactive** | 追问交互指令，控制前端展示什么组件 |

---

> **文档维护说明**: 本文档随项目迭代同步更新。新增设计决策、修改分层边界时，需同步更新。

## License

MIT
