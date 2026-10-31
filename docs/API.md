# BuildChoice · MCP 接口

本文面向插件集成与开发者。日常使用可直接在 Codex 对话中提出需求，见[决策卡指南](DECISION_GUIDANCE.md)。BuildChoice 通过 MCP 提供决策引导、项目记忆、实现关联、行为验证及文件证据接口。

## 连接与可用工具

安装器绑定目标工作区、Python 和运行时。启用原生设置与决策卡时提供 15 个工具：

| 分组 | 工具 |
|---|---|
| 设置 | buildchoice_settings_read、buildchoice_settings_update、buildchoice_settings_status |
| 证据与兼容审计 | buildchoice_audit_start、buildchoice_audit_read、buildchoice_audit_decision、buildchoice_audit_report |
| 决策 | buildchoice_screen_candidates、buildchoice_card_activate、buildchoice_decision_status、buildchoice_decision_prepare_revision |
| 实现与验证 | buildchoice_link_implementation、buildchoice_acceptance_prepare、buildchoice_verify_decision |
| 项目记忆 | buildchoice_memory |

决策卡关闭时隐藏决策写入、实现关联、验收/验证和记忆工具，保留 8 个工具；完全关闭时仅保留设置与决策状态，共 4 个。工具列表变更会发送通知，调用时仍执行开关校验。

会话句柄来自实际 UserPromptSubmit Hook。创建或访问可信任务时须传入当前有效句柄；自行填写 session_id 或复述“用户已同意”不能建立可信确认。工具调用不授予文件、网络或命令执行许可。

## 读取文件证据

先创建来源收集会话：

~~~json
{"title":"小票保存规则","task":"核对已确认保存流程的相关资料"}
~~~

调用 buildchoice_audit_start，取得返回的会话 id，再调用 buildchoice_audit_read：

~~~json
{"session":"audit-...","path":"examples/receipt_review/receipt.json"}
~~~

该路径是仓库内示例；实际集成应换成绑定项目内的文件。读取器返回 id、content、locator、digest 和读取时间。引用使用返回的 source_id，以及 JSON pointer 或精确 quote：

~~~json
{"source_id":"src-...","pointer":"/amount"}
~~~

来源收集会话的 task 是调用方说明，不是用户授权。文件读取与引用绑定可以证明内容、路径和哈希，不证明业务解释正确。

## 兼容审计记录

已有集成可继续使用 buildchoice_audit_decision(session, title, value, refs, impact?, rationale?) 登记引用，用 buildchoice_audit_report(session) 获取 report 与 markdown。引用在 pointer 与 quote 中选择一项，必须来自当前来源收集会话。

这些记录与 V3 的用户确认分别保存，不生成可信用户选择。报告中的 linked 表示字面值匹配，attention 表示缺失、变化或待核对，reviewed 表示已有复核意见；均不等于行为测试通过。

## 项目决策记忆

buildchoice_memory(query="", include_archived=false, session_handle) 需要当前有效 Hook 句柄，返回 memory.v1、最多 30 条参考/规则、确认来源、生命周期、冲突、total_matches、truncated 和精确管理命令。查询不续期，也不创建确认；管理操作通过真实用户消息执行。见[决策记忆](DECISION_MEMORY.md)。

Decision 可包含记忆匹配来源。project_rule_reused 不等于本任务的用户确认，不能直接用来创建仅接受本任务确认的验收集合。状态查询会重新核对复用规则的有效性。

候选的 memory_intent 为 reuse / change / uncertain，缺省 uncertain。仅核实需求未变且范围一致时使用 reuse；change 或 uncertain 不会静默沿用长期规则。自动复用还要求字段、类别与选项含义一致；没有结构化 value 时标签与后果也须一致。匹配结果为 PROJECT_MEMORY_RULE、confirmation_status=project_rule_reused，并保存原确认来源。适用范围的判断仍来自 Agent，不是语义证明。

## 决策引导接口

- `buildchoice_screen_candidates(request)`：校验候选、核对来源并按确定性规则给出四状态，附带 Agent 声明的覆盖依据；按 task_id + idempotency_key 防止重复登记。

筛选的任务/句柄绑定、候选、事件及缓存响应在单一写事务中提交，失败整体回滚。缓存只在所引用文件、未读资源和决定/确认/覆盖快照仍匹配时重放；过期或旧格式缓存返回 `CACHED_SCREEN_STALE`，执行中输入变化返回 `SCREEN_INPUT_CHANGED_DURING_EVALUATION`。前者需读取当前来源/状态后换新键筛选，后者未提交该请求的写入。新筛选的语义指纹不包含连接句柄或重复的 task_id，但先校验当前会话归属；改变候选等语义输入仍拒绝复用同一键。
- `buildchoice_card_activate(task_id, decision_id, revision, idempotency_key, session_handle)`：同会话最多激活一张待答卡，返回固定文本与 delivery_status=not_observed。
- `buildchoice_decision_status(task_id?, session_handle?)`：读取开关、未决项和实际确认历史。可信任务需要当前 Hook 句柄，不能只传 Agent 自报的会话 ID。
- `buildchoice_decision_prepare_revision(task_id, decision_id, revision, candidate, reason, session_handle)`：追加新版本，清除旧卡激活状态，新版本必须重新得到明确选择。

没有将 Agent 声明直接写成可信用户确认的接口。确认来自原生 Hook 的严格回复通道，模拟回调测试与真实宿主验收分别记录。

## 决定与实现关联

`buildchoice_link_implementation(task_id, decision_id, revision, path, note, start_line?, end_line?, session_handle?)` 将工作区真实 UTF-8 文件关联到当前决定版本。path 使用相对路径，note 说明具体关系，行号可省略；文件最大 256 KiB。拒绝越界、私有、链接路径、无效行号、过期版本和跨会话写入。

服务端读取实际文件并保存 SHA256；不执行 Git，不修改文件，不存整段代码快照。同一决定版本/文件/行号重复登记相同内容时不重复写事件；内容或说明变化保留新事件。每任务最多 100 个关联。

返回 provenance=agent_reported_implementation、does_not_prove_correctness=true。该登记不建立用户确认，也不证明实现符合选择。`buildchoice_decision_status` 的 implementations 返回关联、当前 file_status 和 needs_recheck；决定版本变化、文件变化或不可读均提示复核。旧记录保留，关联本身不触发验证。

## 决策落实验证

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
