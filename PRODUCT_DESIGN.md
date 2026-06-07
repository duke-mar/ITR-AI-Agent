# ITR 智能客服 —— 追问与信息收集产品设计方案

> 版本: v1.0  
> 日期: 2026-06-08  
> 状态: 设计确认阶段

---

## 一、设计目标

解决纯自然语言追问的三大痛点：
1. **用户回复不相关**（闲聊、新闻、情绪发泄）→ 数据污染
2. **用户回复格式错误**（手机号少一位、订单号带字母）→ 提取失败
3. **大模型追问成本高**（每轮追问都调 LLM）→ 不经济

**核心思路**：把"补充信息"按字段类型分类，不同类型用不同交互方式处理。

---

## 二、字段类型三分法

所有需要收集的信息，按交互方式分为三类：

| 类型 | 名称 | 交互方式 | 前端展示 | 后端处理 | 示例 |
|------|------|---------|---------|---------|------|
| **A类** | 开放文本 | 第一轮由 LLM 从用户原始消息提取 | 无需追问，已前置收集 | LLM 提取 | 操作步骤、报错信息、问题描述 |
| **B类** | 枚举选项 | 前端显示选项卡片，用户点击选择 | 卡片/按钮组 | 直接写入，100%准确 | 账号类型、产品模块、套餐类型 |
| **C类** | 规则格式 | 前端输入框 + 格式提示 | 输入框（带样例提示） | 正则提取 / API验证 | 手机号、邮箱、订单号 |

---

## 三、完整对话流程

### 3.1 第一轮：用户提问

```
用户输入: "我的系统报错了，点击查询按钮就提示500错误，请问怎么办？"
    │
    ▼
┌─────────────────────────────────────────┐
│ 【意图识别节点】                          │
│ 1. LLM 识别意图 → technical              │
│ 2. LLM 提取开放文本字段（A类）            │
│    - operation_steps: "点击查询按钮"      │
│    - error_message: "500错误"             │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 【信息收集节点】                          │
│ 检查缺失字段：                            │
│   - B类: product_module ❌ 缺失           │
│   - C类: browser_version ❌ 缺失          │
│                                         │
│ 决策：还有缺失字段，进入追问流程           │
└─────────────────────────────────────────┘
    │
    ├─ 追问 B类字段: product_module
    │     → 给前端发送 "show_options" 指令
    │
    └─ 追问 C类字段: browser_version
          → 给前端发送 "ask_input" 指令
    │
    ▼
本轮结束（END），等待用户操作
```

### 3.2 第二轮：用户点击选项 / 输入规则字段

```
用户点击 "📦 订单模块" 选项卡片
    │
    ▼
前端发送: {"type": "field_fill", "field_id": "product_module", "value": "order"}
    │
    ▼
后端直接写入 collected_info.product_module = "order"
    │
    ▼
检查是否还有缺失字段：
  - C类: browser_version ❌ 仍缺失
    │
    ▼
继续追问 C类: browser_version
  → 给前端发送 "ask_input" 指令
    │
    ▼
本轮结束（END）
```

### 3.3 第三轮：用户输入规则字段

```
用户在输入框输入: "Chrome 120"
    │
    ▼
前端发送: {"type": "text", "content": "Chrome 120"}
    │
    ▼
后端正则提取:
  - 匹配到 "Chrome" → browser_version = "chrome"
  - 写入 collected_info
    │
    ▼
检查是否还有缺失字段：✅ 全部收集完成
    │
    ▼
路由到方案生成节点
    │
    ▼
生成回复："根据您描述的问题，订单模块查询报错500，建议您..."
```

### 3.4 异常流：规则字段格式错误

```
后端追问 C类: order_id
  → 给前端发送 "ask_input" 指令（带样例提示）
    │
    ▼
用户输入: "abc123"（格式错误，应为纯数字）
    │
    ▼
后端正则提取失败 ❌
    │
    ▼
回复用户："订单号格式不正确，应为12-20位数字，例如：2024010112345678，请重新输入"
    │
    ▼
本轮结束（END），等待用户重新输入
    │
    ▼
用户重新输入: "2024010112345678"
    │
    ▼
后端正则提取成功 ✅ → 继续后续流程
```

---

## 四、前后端消息协议

### 4.1 后端 → 前端（追问指令）

#### A. 显示选项卡片（B类字段）

```json
{
  "type": "ask_options",
  "field_id": "account_type",
  "field_label": "账号类型",
  "question": "请问您的账号类型是什么？",
  "options": [
    {"value": "phone", "label": "📱 手机号"},
    {"value": "email", "label": "📧 邮箱"},
    {"value": "wechat", "label": "💬 微信"},
    {"value": "qq", "label": "🐧 QQ号"}
  ]
}
```

#### B. 请求规则输入（C类字段）

```json
{
  "type": "ask_input",
  "field_id": "order_id",
  "field_label": "订单号",
  "question": "请输入您的订单号",
  "placeholder": "例如：2024010112345678",
  "example": "2024010112345678",
  "hint": "订单号为12-20位数字",
  "pattern": "\\d{12,20}"
}
```

#### C. 普通回复

```json
{
  "type": "reply",
  "content": "根据您描述的问题...",
  "intent": "technical",
  "status": "active"
}
```

#### D. 格式错误提示

```json
{
  "type": "error_hint",
  "field_id": "order_id",
  "content": "订单号格式不正确，应为12-20位数字，例如：2024010112345678，请重新输入"
}
```

### 4.2 前端 → 后端（用户响应）

#### A. 点击选项卡片

```json
{
  "type": "field_fill",
  "field_id": "account_type",
  "value": "phone",
  "label": "📱 手机号"
}
```

#### B. 文本输入（规则字段）

```json
{
  "type": "text",
  "content": "2024010112345678"
}
```

#### C. 普通消息

```json
{
  "type": "text",
  "content": "我的系统报错了"
}
```

---

## 五、前端交互组件设计

### 5.1 选项卡片组件（ask_options）

```
┌─────────────────────────────────────┐
│  🤖 请问您的账号类型是什么？          │
│                                     │
│  ┌──────────┐ ┌──────────┐         │
│  │  📱 手机号 │ │  📧 邮箱  │         │
│  └──────────┘ └──────────┘         │
│  ┌──────────┐ ┌──────────┐         │
│  │  💬 微信  │ │  🐧 QQ号 │         │
│  └──────────┘ └──────────┘         │
└─────────────────────────────────────┘
```

- 用户点击后直接发送 `field_fill` 消息
- 点击后按钮置灰，防止重复选择

### 5.2 规则输入组件（ask_input）

```
┌─────────────────────────────────────┐
│  🤖 请输入您的订单号                │
│  💡 提示：订单号为12-20位数字        │
│  💡 例如：2024010112345678          │
│                                     │
│  ┌────────────────────────────────┐ │
│  │  2024010112345678              │ │
│  └────────────────────────────────┘ │
│              [发送]                  │
└─────────────────────────────────────┘
```

- 输入框下方显示格式提示和样例
- 前端可做基础校验（如纯数字），但不做强制拦截
- 后端正则提取失败时，显示红色错误提示

### 5.3 错误提示组件（error_hint）

```
┌─────────────────────────────────────┐
│  ⚠️ 订单号格式不正确                 │
│  应为12-20位数字                     │
│  例如：2024010112345678              │
│  请重新输入                          │
└─────────────────────────────────────┘
```

---

## 六、后端处理逻辑

### 6.1 第一轮处理（意图识别 + 开放文本提取）

```python
async def execute(self, state):
    # 1. 识别意图
    intent = await self.llm.classify_intent(user_msg)
    
    # 2. 提取开放文本字段（A类）
    open_text_fields = self.intent_registry.get_open_text_fields(intent)
    for field in open_text_fields:
        value = await self.llm.extract_field(user_msg, field.extraction_prompt)
        collected_info[field.id] = value
    
    # 3. 初始化枚举和规则字段为 None
    enum_and_rule_fields = self.intent_registry.get_enum_and_rule_fields(intent)
    for field_id in enum_and_rule_fields:
        if field_id not in collected_info:
            collected_info[field_id] = None
    
    return {"intent": intent, "collected_info": collected_info}
```

### 6.2 信息收集节点（追问逻辑）

```python
async def execute(self, state):
    intent = state.get("intent")
    collected = state.get("collected_info", {})
    intent_config = self.intent_registry.get(intent)
    
    # 检查缺失字段
    missing = [f for f in intent_config.get_all_field_ids() if collected.get(f) is None]
    
    if not missing:
        # 所有字段收集完成
        return {"info_complete": True}
    
    # 找到第一个缺失字段
    field_id = missing[0]
    field_config = intent_config.get_field(field_id)
    
    # 根据字段类型发送不同的追问指令
    if isinstance(field_config, EnumField):
        # B类：发送选项卡片指令
        return {
            "interactive": {
                "type": "ask_options",
                "field_id": field_id,
                "field_label": field_config.label,
                "options": [{"value": opt.value, "label": opt.label} for opt in field_config.options]
            }
        }
    
    elif isinstance(field_config, RuleField):
        # C类：发送规则输入指令
        return {
            "interactive": {
                "type": "ask_input",
                "field_id": field_id,
                "field_label": field_config.label,
                "example": field_config.example,
                "hint": f"格式要求：{field_config.pattern}"
            }
        }
```

### 6.3 用户响应处理（app.py）

```python
# 处理前端发来的 field_fill 消息
if msg_type == "field_fill":
    field_id = msg.get("field_id")
    value = msg.get("value")
    state["collected_info"][field_id] = value
    # 不经过 LLM，直接写入
    
# 处理文本输入（可能是规则字段或普通消息）
elif msg_type == "text":
    # 检查当前是否在追问规则字段
    current_field = self._get_current_asking_field(state)
    field_config = self.intent_registry.get_field(current_field)
    
    if isinstance(field_config, RuleField):
        # C类：正则提取
        import re
        match = re.search(field_config.pattern, user_content)
        if match:
            state["collected_info"][current_field] = match.group(0)
        else:
            # 格式错误，发送错误提示
            await websocket.send_json({
                "type": "error_hint",
                "field_id": current_field,
                "content": field_config.error_message + f" 例如：{field_config.example}"
            })
            continue  # 不进入 Graph，等待用户重新输入
```

---

## 七、字段配置示例（YAML）

```yaml
id: billing
name: 计费问题

# A类：开放文本（第一轮 LLM 提取）
open_text_fields:
  - id: refund_reason
    label: 退款原因
    extraction_prompt: "用户申请退款的原因是什么？"

# B类：枚举选项（前端卡片）
enum_fields:
  - id: plan_type
    label: 套餐类型
    required: true
    options:
      - value: basic
        label: 🔰 基础版
      - value: pro
        label: ⭐ 专业版
      - value: enterprise
        label: 🏢 企业版

# C类：规则格式（正则/API验证）
rule_fields:
  - id: order_id
    label: 订单号
    required: true
    type: regex
    pattern: '\d{12,20}'
    example: "2024010112345678"
    error_message: "订单号应为12-20位数字"
    
  - id: order_time
    label: 订单时间
    required: false
    type: regex
    pattern: '\d{4}[年/-]\d{1,2}[月/-]\d{1,2}'
    example: "2024-01-01"
    error_message: "请提供正确的日期格式"
```

---

## 八、与传统方案对比

| 维度 | 传统方案（纯LLM追问） | 本方案（分类处理） |
|------|---------------------|------------------|
| **追问准确性** | 低（用户回复不相关也收集） | 高（选项100%准确，正则验证格式） |
| **LLM调用次数** | 每轮追问都调LLM | 第一轮调1次，后续不调 |
| **成本** | 高 | 低（降低60%以上） |
| **用户体验** | 一般（自由输入，容易出错） | 好（选项卡片点击即完成） |
| **实现复杂度** | 低（一个Prompt搞定） | 中（需要前后端协议配合） |
| **数据质量** | 差（可能混入无关内容） | 高（结构化数据，可验证） |

---

## 九、已确认的产品决策

### 决策1：所有非选项追问必须提供样例

除了B类枚举选项卡片外，**所有追问场景**（A类开放文本、C类规则字段）都必须：
- 前端显示样例提示
- 后端用正则识别
- 识别失败则提示："您输入的格式不对，无法识别，请重新按照样例格式输入"

### 决策2：正则失败次数处理策略

| 失败次数 | 处理方式 | 前端展示 |
|---------|---------|---------|
| 1-3次 | 提示格式错误，要求重新输入 | 错误提示 + 样例 |
| 超过3次 | 提示格式错误 + **提供转人工选项** | 错误提示 + "或转接人工客服" |
| 超过5次 | **强行转接人工服务** | 进入人工排队状态 |

### 决策3：人工排队状态设计

- 用户聊天框**依然可以输入**
- 提供**"取消人工"小卡片**供用户点击
- 用户输入"取消"、"算了"等关键词可放弃排队（MVP阶段用关键词匹配，后续优化为大模型识别）
- 优先排队机制：记录在文档中，代码层暂不实现（无坐席系统）

### 决策4：开放文本提取失败处理

第一轮LLM提取开放文本字段失败时，**追加文本追问**（带样例格式），不直接允许为空。

### 决策5：用户跳过字段

**必填字段不允许跳过**。所有字段必须完成收集或明确标记为"用户拒绝提供"（通过特定选项实现）。

### 决策6：字段依赖关系

**MVP暂不支持字段依赖**。所有字段平铺展示，后续版本通过YAML的 `depends_on` 配置支持。

---

## 十、下一步行动

1. **✅ 产品方案确认完毕**
2. **输出技术实现方案** → 前后端接口文档 + Node代码逻辑
3. **开发实现** → 按模块逐步开发
4. **测试验证** → 覆盖正常流和异常流
