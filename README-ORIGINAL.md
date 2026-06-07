# ITR 智能客服机器人 — MVP Demo 架构设计文档

> **版本**: v1.0  
> **日期**: 2026-06-07  
> **定位**: 面向商业级客服机器人的可扩展架构设计，当前阶段为 MVP Demo 可自行扩展

---

## 一、架构核心理念

### 1.1 设计目标

| 目标 | 说明 |
|-----|------|
| **配置驱动** | 业务数据（意图、字段、话术）外置到配置文件，新增业务线 = 新增配置，零代码改动 |
| **关注点分离** | 流程编排、业务逻辑、LLM 调用、状态管理完全解耦 |
| **契约化接口** | Node 之间通过明确接口交互，不直接读写对方状态 |
| **插件化架构** | 新增外部能力 = 新增一个 Skill 文件，Node 按需注入 |
| **分层清晰** | 表现层、编排层、领域层、应用层、基础设施层职责边界明确 |

### 1.2 核心原则

> **配置即代码，但配置不等于代码。**  
> 代码只保留"如何执行"的机制，不保留"执行什么"的数据。

---

## 二、架构分层设计

```
┌─────────────────────────────────────────────────────────────┐
│  表现层 (Presentation)                                       │
│  WebSocket/HTTP Gateway │ 消息适配器 │ 会话生命周期管理        │
├─────────────────────────────────────────────────────────────┤
│  编排层 (Orchestration) —— 保留 LangGraph                     │
│  声明式工作流引擎 │ 事件总线 │ 状态机 │ Checkpoint 管理         │
├─────────────────────────────────────────────────────────────┤
│  领域层 (Domain) —— 核心，纯接口 + 纯数据结构                  │
│  Intent │ Field │ Conversation │ Event │ NodeContract         │
├─────────────────────────────────────────────────────────────┤
│  应用层 (Application) —— 你的主战场                           │
│  Node 实现 │ Prompt 管理 │ 信息提取策略 │ 业务规则引擎          │
├─────────────────────────────────────────────────────────────┤
│  基础设施层 (Infrastructure)                                  │
│  LLM Skill │ RAG Skill │ DB Skill │ OrderSkill │ TicketSkill  │
├─────────────────────────────────────────────────────────────┤
│  配置层 (Configuration) —— 驱动上层所有行为                    │
│  intents/*.yaml │ workflow.yaml │ prompts/*.j2                │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 各层职责详解

#### 表现层 (Presentation)
- **职责**: 接收用户消息、发送回复、管理 WebSocket 连接生命周期
- **不碰**: 业务逻辑、路由判断、State 内部结构
- **关键文件**: `app.py`

#### 编排层 (Orchestration)
- **职责**: 定义 Node 连接拓扑、条件跳转、State 合并与 Checkpoint 管理
- **技术选型**: **保留 LangGraph**，利用其成熟的 checkpoint 和 reducer 机制
- **关键文件**: `core/graph_builder.py`
- **路由集中化**: 所有路由逻辑从 Node 内部剥离，集中在 Graph 层管理

#### 领域层 (Domain)
- **职责**: 定义核心数据结构和接口契约
- **关键文件**: `core/state.py`、`core/node_interface.py`
- **设计原则**: 纯接口，无实现，无外部依赖

#### 应用层 (Application)
- **职责**: 实现具体业务逻辑（意图识别、信息收集、方案生成等）
- **关键文件**: `nodes/*.py`
- **核心工作**: 构造 Prompt → 调用 Skill → 解析结果 → 返回 StateUpdates

#### 基础设施层 (Infrastructure)
- **职责**: 对接外部服务，无业务语义
- **关键文件**: `skills/*.py`
- **设计原则**: 无状态、可独立测试、可横向替换（换厂商 = 换实现类）

#### 配置层 (Configuration)
- **职责**: 驱动上层所有业务行为
- **关键文件**: `config/intents/*.yaml`、`config/workflow.yaml`
- **使用者**: 产品/运营直接编辑，开发不介入

---

## 三、五大关键设计决策

### 决策 1: 路由保留 LangGraph 方式，但集中管理

- **Node 只负责 `execute()`**，不碰路由逻辑
- 路由规则集中到 `core/graph_builder.py` 的 `_route_*` 方法中
- MVP 阶段路由写死在 Python 中，后续可外部化到 YAML

```python
# Node 层 —— 纯业务逻辑
class IntentRecognitionNode(INode):
    async def execute(self, state: ITRState) -> Dict[str, Any]:
        # 只做意图识别，返回 State 更新
        return {"intent": result.intent}

# Graph 层 —— 集中路由
class GraphBuilder:
    def _route_intent(self, state: ITRState) -> str:
        if state.get("intent") == "greeting":
            return END
        return "info_collection"
```

### 决策 2: Skill 按外部服务边界封装

一个外部服务 = 一个 Skill 类。按服务边界而非功能边界划分：

| Skill | 对接对象 | 示例方法 |
|-------|---------|---------|
| `RAGSkill` | 知识库系统 | `search(query, top_k)` |
| `DifyRAGSkill` | Dify 平台 | `search(query, top_k)` |
| `RAGFlowSkill` | RAGFlow 平台 | `search(query, top_k)` |
| `OrderSystemSkill` | 订单系统 | `query_order(order_id)` |
| `TicketSystemSkill` | 工单系统 | `create_ticket(title, content)` |
| `DBSkill` | 数据库 | `save_session()`, `get_history()` |

Node 通过依赖注入获取 Skill：

```python
class SolutionGenerationNode(INode):
    def __init__(self, rag: RAGSkill, order: Optional[OrderSystemSkill] = None):
        self.rag = rag
        self.order = order
```

### 决策 3: LLM 封装为独立 Skill，Prompt 写在 Node 层

**LLM Skill 是纯通信层**：
- 只负责发 HTTP 请求、收响应、异常处理、重试熔断
- 不碰 Prompt、不碰业务语义
- 兼容所有 OpenAI 格式 API（DeepSeek、通义、Moonshot、OpenAI）

**Prompt 写在 Node 实现层**：
- 意图识别 Prompt 在 `IntentRecognitionNode`
- 槽位提取 Prompt 在 `InfoCollectionNode`
- 方案生成 Prompt 在 `SolutionGenerationNode`

**前期统一为一个 LLMSkill**：

```python
class LLMSkill:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def complete(self, prompt: str, **kwargs) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )
        return response.choices[0].message.content
```

切厂商 = 改配置（`base_url` + `model`），不新建类。

### 决策 4: LangGraph 保留作为状态机底座

自研状态机的成本和风险不明确，LangGraph 的以下能力在 MVP 阶段直接复用：

- **Checkpoint 机制**: 跨 invoke 调用保持 State 连续性
- **Reducer 机制**: 字段级状态合并策略
- **并发控制**: 同一线程的状态隔离
- **调试工具**: `graph.get_state()` 可回溯任意步骤

### 决策 5: 追问场景下意图识别与处理

关键设计：意图切换的判定策略

不能用户随便说句话就切换意图，否则追问永远完不成。常见策略：

**策略1：置信度阈值**

```python
if (recognized_intent != prev_intent
    and confidence > 0.85):  # ← 只有高置信度才切换
    # 切换意图
```

**策略2：关键词快速拦截**

```python
# 如果用户消息包含明显的"转话题"信号，直接切换
SWITCH_SIGNALS = ["算了", "换个问题", "不问了", "那我换个", "还是问"]

if any(signal in last_msg for signal in SWITCH_SIGNALS):
    # 用户明确要切换话题，按新意图处理
```

**策略3：LLM 二次确认（最准但最慢）**

```python
prompt = f"""用户在客服追问过程中回复了："{last_msg}"
当前在追问：{current_question}
请判断用户是：
A. 正常补充信息
B. 切换话题（不想回答这个问题了）
C. 要求转人工
只输出 A/B/C"""

result = await self.llm.complete(prompt)
if result == "B":
    # 切换话题，重新识别意图
```

**行业内的真实做法**

| 场景 | 处理方式 |
|------|---------|
| 用户正常补充 | 保持原意图，合并信息 |
| 用户说"算了，不问了" | 视为意图切换，重新识别 |
| 用户说"转人工" | 高优先级打断，立即处理 |
| 用户闲聊"今天天气真好" | 礼貌回应后，拉回追问 |
| 用户说"我问一下账号问题" | 明确切换信号，重置状态 |

**阿里小蜜的做法**（公开论文里提到的）：
- 每轮都跑意图识别（双塔模型，毫秒级）
- 追问状态下，意图模型会屏蔽业务意图，优先判定为 supplement
- 只有当用户明确说"我想问别的"或包含转人工词时，才解除屏蔽

---

## 四、State 设计规范

### 4.1 State 的本质

> **State 是"这次对话的临时草稿纸"**，是 LangGraph 在一次会话流程中跨 Node 传递的**共享上下文**。  
> **数据库是"正式档案柜"**，保存需要长期保留的业务数据。

### 4.2 State 里放什么？

**应该放的（临时上下文）**:

| 字段 | 作用 | 写入方 | 读取方 |
|-----|------|--------|--------|
| `messages` | 对话历史，LLM 上下文来源 | `app.py`、所有 Node | 所有 Node |
| `intent` | 当前意图，路由判断依据 | `intent_recognition` | `info_collection`、路由 |
| `collected_info` | 已收集字段，信息收集载体 | `intent_recognition`、`info_collection` | `solution_generation`、路由 |
| `info_collection_round` | 追问轮数，超限判断 | `info_collection` | `intent_recognition`、路由 |
| `round_count` | 总轮数，防止无限对话 | `app.py` | 所有 Node、路由 |
| `last_node` | 上一个执行节点，兜底逻辑 | 所有 Node | `intent_recognition` |
| `status` | 会话状态，特殊交互判断 | `session_end` | `app.py`、前端 |
| `info_complete` | 信息是否完整，路由判断 | `info_collection` | 路由 |

**不应该放的（持久化业务数据）**:

| 数据 | 正确做法 |
|-----|---------|
| 用户画像/会员等级 | 从用户服务实时查，或存数据库 |
| 订单详情 | 从 `OrderSystemSkill` 实时查 |
| 知识库文档 | 从 `RAGSkill` 实时查 |
| 工单历史 | 从 `TicketSystemSkill` 实时查 |
| 满意度评分（已提交） | 直接写入数据库业务表 |

### 4.3 保留变量（改名需全局同步）

以下字段被多处代码硬依赖，**删除或改名需要同步修改所有引用处**：

| 字段名 | 依赖方 | 影响面 |
|-------|--------|--------|
| `messages` | 所有 Node、`app.py`、前端 | **极高** |
| `status` | `app.py`（特殊交互）、`session_end` | **极高** |
| `intent` | 路由、`info_collection`、`solution_generation` | **高** |
| `collected_info` | `intent_recognition`、`info_collection`、`solution_generation` | **高** |
| `round_count` | `app.py`、所有 Node（超限判断） | **高** |
| `info_collection_round` | `info_collection`、`intent_recognition`（兜底） | **中** |
| `last_node` | 所有 Node（写入）、`intent_recognition`（读取） | **中** |
| `info_complete` | `info_collection`（写入）、路由（读取） | **中** |

**可自由新增字段**，只要名字不冲突、类型可 JSON 序列化。

### 4.4 State 与数据库的分工

| 数据类型 | State | 数据库 | 说明 |
|---------|-------|--------|------|
| 当前对话历史 | ✅ 必须有 | ✅ 归档保存 | State 用于 LLM 上下文；数据库用于审计 |
| 当前意图 | ✅ | ❌ | 临时状态，不需要长期保存 |
| 已收集字段 | ✅ | ✅ 归档 | State 推进流程；数据库保存完整会话 |
| 追问轮数 | ✅ | ❌ | 纯临时计数器 |
| 用户画像 | ❌ | ✅ | 从用户服务/数据库实时查 |
| 订单详情 | ❌ | ✅ | 从订单系统 Skill 实时查 |
| 满意度评分 | ❌ | ✅ | 直接写入数据库业务表 |
| Prompt 调用日志 | ❌ | ✅ | 用于 A/B 测试效果追踪 |

---

## 五、MemorySaver 详解

### 5.1 是什么？

MemorySaver 是 LangGraph 提供的**内置内存 Checkpoint 持久化器**。它在每次 `graph.invoke()` 执行后，将当前完整 State 保存到内存中。下次用相同的 `thread_id` 调用时，LangGraph 自动从内存恢复上次 State，与新传入的数据合并后继续执行。

**类比游戏存档点**：打完第一关存个档，下次开机从存档继续，而不是从头再来。

### 5.2 核心机制

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# 第一次调用 —— 创建存档
config = {"configurable": {"thread_id": "user_001"}}
result1 = graph.invoke(state1, config=config)
# MemorySaver 自动保存最终 State

# 第二次调用 —— 从存档恢复，继续执行
result2 = graph.invoke(state2, config=config)
# LangGraph 自动读取上次存档，合并 state2，继续执行
```

**thread_id 是唯一标识**：
- 相同 `thread_id` → 共享同一个存档，对话连续
- 不同 `thread_id` → 互相隔离，相当于两个独立用户

### 5.3 使用场景

| 场景 | 说明 |
|-----|------|
| **多轮对话** | 最核心场景。用户分多条消息输入，对话必须连续 |
| **断线重连** | WebSocket 断开后恢复，从 Checkpoint 继续 |
| **人机协作** | 流程中断转人工，处理完后从 Checkpoint 恢复 |
| **调试回溯** | `graph.get_state(config)` 可查看任意步骤的完整状态 |
| **错误恢复** | 某节点失败后，可从上一个 Checkpoint 重试 |

### 5.4 局限与生产替代

| 特性 | MemorySaver | 生产级替代（PostgresSaver / RedisSaver） |
|-----|-------------|----------------------------------------|
| 存储位置 | 内存 | PostgreSQL / Redis |
| 服务重启后 | **数据全丢** | 数据保留 |
| 分布式部署 | 不支持（每台机器内存独立） | 支持（共享存储） |
| 适用场景 | 单机 MVP / 本地开发 | 生产环境 |
| 配置复杂度 | 零配置 | 需要数据库连接 |

### 5.5 状态合并的潜在陷阱

当第二次 `graph.invoke()` 调用时，LangGraph 执行以下步骤：

```
1. 从 MemorySaver 读取上次存档 State_checkpoint
2. 和新传入的 State_input 合并 → State_merged
3. 执行 Node，Node 返回 Updates
4. 把 Updates 应用到 State_merged → State_final
5. 保存 State_final 回 MemorySaver
```

**步骤 2 的合并逻辑是字段级覆盖**（对 TypedDict 默认行为）。如果 `State_input` 和 `State_checkpoint` 中的某个字段值不一致，可能导致意外覆盖。

**建议**: 对 `collected_info` 等 dict 类型字段，自定义 Reducer 实现增量合并：

```python
def merge_dict(left: Dict, right: Dict) -> Dict:
    """字典增量合并，而非完全覆盖"""
    result = dict(left)
    result.update(right)
    return result
```

---

## 六、MVP Demo 目录结构

```
itr-orchestrator-demo/
├── config/                          # 【你编辑】业务配置
│   ├── intents/
│   │   ├── technical.yaml           # 意图定义：字段、标签、校验规则
│   │   ├── account.yaml
│   │   └── billing.yaml
│   ├── workflow.yaml                # 流程定义（MVP 可先写代码）
│   └── prompts/                     # Prompt 模板（Node 可引用）
│       ├── intent_recognition.j2
│       └── slot_extraction.j2
│
├── src/
│   ├── core/                        # 【框架层】MVP 期间基本不动
│   │   ├── __init__.py
│   │   ├── graph_builder.py         # LangGraph 编排器：注册 Node、配置路由
│   │   ├── state.py                 # 全局 State 定义 + 自定义 Reducer
│   │   ├── node_interface.py        # INode 抽象接口
│   │   └── skill_registry.py        # Skill 注册与依赖注入
│   │
│   ├── nodes/                       # 【你写】业务逻辑 + Prompt 工程
│   │   ├── __init__.py
│   │   ├── intent_recognition.py    # 意图识别 Node
│   │   ├── info_collection.py       # 信息收集 Node
│   │   ├── solution_generation.py   # 方案生成 Node
│   │   └── session_end.py           # 会话结束 Node
│   │
│   ├── skills/                      # 【你封装】外部服务适配器
│   │   ├── __init__.py
│   │   ├── base.py                  # BaseSkill 接口
│   │   ├── llm_skill.py             # 统一 LLM（兼容 OpenAI 格式）
│   │   ├── rag_skill.py             # RAG 检索（可接 Dify/RAGFlow）
│   │   ├── db_skill.py              # 数据库操作
│   │   ├── order_system_skill.py    # 订单系统（预留）
│   │   └── ticket_system_skill.py   # 工单系统（预留）
│   │
│   ├── services/                    # 基础设施客户端初始化
│   │   └── __init__.py
│   │
│   └── app.py                       # FastAPI + WebSocket 入口
│
├── tests/                           # 【你写】单元测试
│   ├── test_nodes/
│   └── test_skills/
│
├── requirements.txt
└── README.md                        # 使用说明与扩展指南
```

---

## 七、各层编码规范

### 7.1 Node 层规范

```python
class IntentRecognitionNode(INode):
    """意图识别 Node
    
    职责:
      - 读取最后一条用户消息
      - 构造 Prompt（含意图列表）
      - 调用 LLMSkill 获取模型响应
      - 解析响应，提取意图标签
      - 返回 State 更新片段
    """
    name = "intent_recognition"
    
    def __init__(self, llm: LLMSkill, intent_registry: IntentRegistry):
        self.llm = llm
        self.intent_registry = intent_registry
    
    def required_skills(self):
        return [LLMSkill]
    
    async def execute(self, state: ITRState) -> Dict[str, Any]:
        # 1. 从 State 读取输入
        last_msg = self._get_last_user_message(state)
        available = self.intent_registry.list_ids()
        
        # 2. 构造 Prompt（Node 层职责）
        prompt = self._build_prompt(last_msg, available)
        
        # 3. 调用 Skill（纯通信）
        raw = await self.llm.complete(prompt, temperature=0.3)
        
        # 4. 解析响应（Node 层职责）
        intent = self._parse_response(raw, available)
        
        # 5. 返回 State 更新片段
        return {
            "intent": intent,
            "intent_confidence": 0.9 if intent != "unknown" else 0.0,
        }
    
    # === 以下为私有方法，Node 内部实现细节 ===
    def _build_prompt(self, message: str, intents: List[str]) -> str: ...
    def _parse_response(self, raw: str, intents: List[str]) -> str: ...
```

**Node 层戒律**:
- ✅ 构造 Prompt、解析响应、业务判断
- ✅ 调用 Skill 获取外部数据
- ❌ 不碰路由逻辑
- ❌ 不直接操作数据库（通过 DBSkill）
- ❌ 不直接操作 WebSocket

### 7.2 Skill 层规范

```python
class LLMSkill(BaseSkill):
    """LLM 通信 Skill
    
    职责:
      - 封装 HTTP 调用细节
      - 处理超时、重试、熔断
      - 返回原始文本，不做业务解析
    """
    
    def __init__(self, api_key: str, base_url: str, model: str, **defaults):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.defaults = defaults
    
    async def complete(self, prompt: str, **override) -> str:
        """单次文本补全，返回原始响应文本"""
        kwargs = {**self.defaults, **override}
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise
```

**Skill 层戒律**:
- ✅ 封装外部服务调用细节
- ✅ 处理网络异常、重试、熔断
- ✅ 无状态设计，可独立测试
- ❌ 不碰 Prompt 构造
- ❌ 不碰业务语义解析
- ❌ 不读写 State

### 7.3 Graph 层规范

```python
class GraphBuilder:
    """LangGraph 编排器
    
    职责:
      - 注册所有 Node（只绑定 execute）
      - 集中配置路由规则
      - 管理 Checkpoint
    """
    
    def build(self) -> StateGraph:
        workflow = StateGraph(ITRState)
        
        # 1. 注册 Node（业务层提供）
        for name, node in self.nodes.items():
            workflow.add_node(name, node.execute)
        
        # 2. 配置条件路由（集中管理）
        workflow.add_conditional_edges(
            "intent_recognition", 
            self._route_intent
        )
        workflow.add_conditional_edges(
            "info_collection",
            self._route_collection
        )
        
        # 3. 设置入口
        workflow.set_entry_point("intent_recognition")
        
        # 4. 编译 + Checkpoint
        checkpointer = MemorySaver()
        return workflow.compile(checkpointer=checkpointer)
    
    def _route_intent(self, state: ITRState) -> str:
        """意图识别后的路由逻辑"""
        intent = state.get("intent")
        if intent == "greeting":
            return END
        if intent == "manual":
            return "session_end"
        return "info_collection"
```

**Graph 层戒律**:
- ✅ 管理 Node 连接关系
- ✅ 集中路由判断
- ✅ 管理 Checkpoint 生命周期
- ❌ 不碰业务逻辑
- ❌ 不构造 Prompt
- ❌ 不调用外部服务

---

## 八、扩展指南

### 8.1 新增一个业务线（如"售后服务"）

1. **创建配置文件**: `config/intents/aftersales.yaml`
2. **无需修改任何代码**
3. Node 会自动读取配置，按新意图的字段结构执行收集

### 8.2 新增一个 Node（如"满意度调研"）

1. **实现 Node**: `src/nodes/satisfaction_survey.py`
   - 继承 `INode`
   - 实现 `execute()`
2. **注册 Node**: 在 `GraphBuilder.build()` 中添加 `workflow.add_node(...)`
3. **配置路由**: 在对应的 `_route_*` 方法中添加跳转条件

### 8.3 新增一个 Skill（如"物流查询"）

1. **实现 Skill**: `src/skills/logistics_skill.py`
   - 继承 `BaseSkill`
   - 封装物流系统 API 调用
2. **注入 Node**: 在需要使用物流查询的 Node `__init__` 中注入
3. **声明依赖**: 在 Node 的 `required_skills()` 中声明

### 8.4 切换 LLM 厂商

1. **修改配置**: 改 `base_url` 和 `model`（如从 DeepSeek 切到通义）
2. **无需修改 Skill 代码**（统一 OpenAI 格式）
3. **无需修改 Node 代码**

### 8.5 新增一个 Graph（如"VIP 快速通道"）

```python
vip_graph = GraphBuilder() \
    .add_node("intent", IntentRecognitionNode) \
    .add_node("priority_check", PriorityCheckNode) \
    .add_node("human", HumanTransferNode) \
    .add_transition("intent", "priority_check") \
    .add_transition("priority_check", "human", condition="is_vip") \
    .build()
```

**大部分 Node 和 Skill 可复用**，只新增差异部分。

---

## 九、常见陷阱与避坑指南

| 陷阱 | 原因 | 解决方案 |
|-----|------|---------|
| State 字段被意外覆盖 | LangGraph 默认 Reducer 是覆盖，非合并 | 对 dict/list 类型自定义 Reducer |
| Node 直接操作数据库 | 绕过 Skill 层，耦合基础设施 | 所有外部操作必须通过 Skill |
| Prompt 写在 Skill 里 | Skill 混入业务语义，难以替换厂商 | Prompt 必须写在 Node 层 |
| Skill 持有状态 | Skill 变成有状态，无法独立测试 | Skill 必须无状态，状态走 State |
| MemorySaver 数据丢失 | 内存存储，服务重启清空 | MVP 可用，生产替换为 PostgresSaver |
| thread_id 重复使用 | 不同用户共享相同 thread_id | 用 session_id / user_id 作为 thread_id |
| 全量 State 传入 invoke | 可能导致 Checkpoint 合并冲突 | 只传入增量输入，或禁用 Checkpoint 验证 |

---

## 十、术语表

| 术语 | 说明 |
|-----|------|
| **Node** | LangGraph 流程中的一个执行节点，封装一段业务逻辑 |
| **Skill** | 外部服务适配器，无业务语义，可独立测试和替换 |
| **State** | LangGraph 在一次会话中跨 Node 共享的临时上下文 |
| **Checkpoint** | LangGraph 在每次 super-step 后保存的状态快照 |
| **thread_id** | Checkpoint 的唯一标识，相同 thread_id 共享对话历史 |
| **MemorySaver** | LangGraph 内置的内存 Checkpoint 持久化器 |
| **Reducer** | LangGraph 的字段级状态合并策略 |
| **Prompt** | 发送给 LLM 的指令文本，在 Node 层构造 |
| **Intent** | 用户咨询的意图类别（如 technical/account） |
| **Slot** | 意图下的信息字段（如 product_module/order_id） |

---

> **文档维护说明**: 本架构文档随项目迭代同步更新。新增设计决策、修改分层边界时，需同步更新本文档。
