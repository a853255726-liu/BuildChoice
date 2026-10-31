# BuildChoice · MCP 与审计接口

0.9 新增 `buildchoice_memory(query="", include_archived=false, session_handle)`，需当前有效 Hook 句柄，返回 memory.v1、最多 30 条参考/规则及来源、生命周期、冲突、截断信息和精确管理命令。只读不续期；无 Agent 写入或批量升级确认的接口。详见[决策记忆](DECISION_MEMORY.md)。Decision 可附 memory 匹配来源；project_rule_reused 不等于本任务的用户确认。状态查询会重算已复用规则的有效性。

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

0.8.3 起，筛选的任务/句柄绑定、候选、事件及缓存响应在单一写事务中提交，失败整体回滚。缓存只在所引用文件、未读资源和决定/确认/覆盖快照仍匹配时重放；过期或旧格式缓存返回 `CACHED_SCREEN_STALE`，执行中输入变化返回 `SCREEN_INPUT_CHANGED_DURING_EVALUATION`。前者需读取当前来源/状态后换新键筛选，后者未提交任何本轮写入。新筛选的语义指纹不包含连接句柄或重复的 task_id，但先校验当前会话归属；改变候选等语义输入仍拒绝复用同一键。
- `buildchoice_card_activate(task_id, decision_id, revision, idempotency_key, session_handle)`：同会话最多激活一张待答卡，返回固定文本与 delivery_status=not_observed。
- `buildchoice_decision_status(task_id?, session_handle?)`：读取开关、未决项和实际确认历史。可信任务需要当前 Hook 句柄，不能只传 Agent 自报的会话 ID。
- `buildchoice_decision_prepare_revision(task_id, decision_id, revision, candidate, reason, session_handle)`：追加新版本，清除旧卡激活状态，新版本必须重新得到明确选择。

没有将 Agent 声明直接写成可信用户确认的接口。确认来自原生 Hook 的严格回复通道，模拟回调测试与真实宿主验收分别记录。

## 决定与实现关联

`buildchoice_link_implementation(task_id, decision_id, revision, path, note, start_line?, end_line?, session_handle?)` 将工作区真实 UTF-8 文件关联到当前决定版本。path 使用相对路径，note 说明具体关系，行号可省略；文件最大 256 KiB。拒绝越界、私有、链接路径、无效行号、过期版本和跨会话写入。

服务端读取实际文件并保存 SHA256；不执行 Git，不修改文件，不存整段代码快照。同一决定版本/文件/行号重复登记相同内容时不重复写事件；内容或说明变化保留新事件。每任务最多 100 个关联。

返回 provenance=agent_reported_implementation、does_not_prove_correctness=true。该登记不建立用户确认，也不证明实现符合选择。`buildchoice_decision_status` 的 implementations 返回关联、当前 file_status 和 needs_recheck；决定版本变化、文件变化或不可读均提示复核。旧记录保留，关联本身不触发验证。

## 决策落实验证（0.8）

- `buildchoice_acceptance_prepare(task_id, decision_id, revision, criteria, session_handle, idempotency_key)`：仅当前会话、当前已确认版本可创建不可变验收集合。每项含 criterion_id、description、basis、required、evidence_type="behavior"、test_ids（实际 unittest 用例 ID）。返回 acceptance_id、acceptance_version、acceptance_digest、实际 confirmation_id 和 choice；criterion_author=agent、human_approval=not_separately_confirmed。新幂等键创建新版本，旧集合不再代表当前验收。
- `buildchoice_verify_decision(task_id, decision_id, revision, acceptance_id, code_evidence_refs, session_handle, idempotency_key, execution_id?)`：读取审计来源及显式采集器记录，保存逐项与整体结论。代码引用含 criterion_id、source_id 以及 quote 或 pointer，真实读取成功仅代表静态绑定。无 execution_id 时不执行任何命令，行为结论保持 inconclusive。拒绝未知、跨任务或跨验收集合的执行记录。

契约：[acceptance.v1](contracts/acceptance-v1.schema.json)、[verification.v1](contracts/verification-v1.schema.json)。后者定义显式 InputManifest、内部 WorkerReport、ExecutionReceipt、CodeEvidenceRef 和 VerificationRun；它们不是可直接提交任意报告的 MCP 接口。

结果含 verdict（passed/failed/inconclusive/error）、criteria、execution_summary、input_snapshot、代码引用、规则与运行时版本；另外动态返回 applicability（current/stale）、stale_reasons 和 current_pass。历史 verdict 不因后来变化而被改写；current_pass 仅表示当前声明范围内的必需条件均通过且证据仍有效。零测试、跳过、缺失映射、仅静态引用均不能通过；实际断言失败为 failed，执行错误/超时为 error。幂等重读也重新计算有效性。

`buildchoice_decision_status` 新增 verification.acceptance_sets / verifications（每决定最新记录）及 history_counts；历史完整记录仍留在 V3 事件表。代码、测试、fixture、配置、清单、采集环境文件、适配器/规则/验证运行时、报告/日志任一变更均可使结果 stale，重跑和重新验证后才产生新的当前结果。它不是对整个 Git 仓库或生产环境的完整证明。

采集命令、权限与范围见 [使用说明](DECISION_VERIFICATION.md)。MCP 无命令参数或自动执行通道。全局 off 或 V3 off 时新增工具隐藏并拒绝调用。

## 覆盖记录与设置

`buildchoice_screen_candidates` 的 request 可带 coverage 数组（最多六项）：dimension、status、reason，可选 evidence_refs 与 candidate_ids。维度与形状见 [Schema](contracts/decision-v3.schema.json)。重复维度或未知候选 ID 会拒绝；缺省 coverage 的旧请求仍接受，返回 reported=false。

响应 coverage 含 provenance=agent_declared、entries、reported 和 does_not_establish_completeness=true。每项独立返回 source_status 与 source_ids。该记录写入 V3 事件，任务状态返回最新一轮；不触发额外推理或参与分流。即使 resolved 引用了真实文件，也仍需判断约束的适用性。

原生设置工具为 `buildchoice_settings_read`、`buildchoice_settings_update`、`buildchoice_settings_status`。mode 仅支持 Prompt 优先 / 完全关闭，decision_guidance 支持关闭 / 试用。不再提供模型开关、模型推断、自动调用或强制调用工具。
