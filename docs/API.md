# BuildChoice · MCP 与审计接口

V3 关键决策引导见 [使用说明](DECISION_GUIDANCE.md) 与 [decision.v3 Schema](contracts/decision-v3.schema.json)。以下 audit.v1 接口签名不变。

## 1. 创建任务

```json
{"title":"接口迁移","task":"检查鉴权与兼容策略"}
```

调用 `buildchoice_audit_start`，返回会话 ID。task 是登记说明，不被当作独立验证的用户授权。

## 2. 读取来源

```json
{"session":"audit-...","path":"examples/migration.json"}
```

调用 `buildchoice_audit_read`。工具从绑定工作区读取 UTF-8 文件，返回 `id`、`content`、`locator`、`digest` 和读取时间。使用返回的来源 ID 登记引用。

## 3. 登记决定

```json
{
  "session":"audit-...",
  "title":"鉴权方式",
  "value":"JWT",
  "refs":[{"source_id":"src-...","pointer":"/auth"}],
  "impact":"接口契约",
  "rationale":"当前配置明确给出鉴权方式"
}
```

每条引用在 `pointer` 与 `quote` 中选择一个：

```json
{"source_id":"src-...","quote":"保留旧接口"}
```

引用必须属于当前会话。没有依据时使用 `refs: []`，账本将显示缺少证据。不同来源的多个 JSON pointer 可以同时核对。

## 4. 获取报告

```json
{"session":"audit-..."}
```

`buildchoice_audit_report` 返回 `report` 和 `markdown`。报告包含来源快照、决定、绑定、问题集合、复核和事件。

| 状态 | 含义 |
|---|---|
| `linked` | 当前引用可定位且结构化字面值匹配 |
| `attention` | 存在缺失、变化、冲突或解释待复核 |
| `reviewed` | 当前状态已有处理意见；原问题保留 |

## 5. 记录复核

工作台或 CLI 支持 `accept`、`revise`、`ask` 三种 disposition，必须附带具体说明。MCP 不提供将 Agent 输出登记为人类复核的自动入口。

## 本地 HTTP

工作台前端使用 `/api/session`、`/api/source`、`/api/decision`、`/api/review`、`/api/sessions` 和 `/api/report`。请求需要启动页面中的本地会话令牌，使用 `X-BuildChoice-Token` 请求头传递。

本地 HTTP 面向单用户工作台；如需集成 Agent，优先使用 MCP。

## V3 对话接口

- `buildchoice_screen_candidates(request)`：校验候选、核对来源并按确定性规则给出四状态，附带 Agent 声明的覆盖依据；按 task_id + idempotency_key 防止重复登记。
- `buildchoice_card_activate(task_id, decision_id, revision, idempotency_key, session_handle)`：同会话最多激活一张待答卡，返回固定文本与 delivery_status=not_observed。
- `buildchoice_decision_status(task_id?, session_handle?)`：读取开关、未决项和实际确认历史。可信任务需要当前 Hook 句柄，不能只传 Agent 自报的会话 ID。
- `buildchoice_decision_prepare_revision(task_id, decision_id, revision, candidate, reason, session_handle)`：追加新版本，清除旧卡激活状态，新版本必须重新得到明确选择。

没有将 Agent 声明直接写成可信用户确认的接口。确认来自原生 Hook 的严格回复通道，模拟回调测试与真实宿主验收分别记录。

## 覆盖记录与设置

`buildchoice_screen_candidates` 的 request 可带 coverage 数组（最多六项）：dimension、status、reason，可选 evidence_refs 与 candidate_ids。维度与形状见 [Schema](contracts/decision-v3.schema.json)。重复维度或未知候选 ID 会拒绝；缺省 coverage 的旧请求仍接受，返回 reported=false。

响应 coverage 含 provenance=agent_declared、entries、reported 和 does_not_establish_completeness=true。每项独立返回 source_status 与 source_ids。该记录写入 V3 事件，任务状态返回最新一轮；不触发额外推理或参与分流。即使 resolved 引用了真实文件，也仍需判断约束的适用性。

原生设置工具为 `buildchoice_settings_read`、`buildchoice_settings_update`、`buildchoice_settings_status`。mode 仅支持 Prompt 优先 / 完全关闭，decision_guidance 支持关闭 / 试用。不再提供模型开关、模型推断、自动调用或强制调用工具。
