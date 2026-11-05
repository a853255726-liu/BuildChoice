# BuildChoice · MCP 接口

LLM 通过 `suggested_action` 提交业务处理建议，程序返回独立的 `validation_status`，核对结构、引用、身份和版本。Option 可带风险解释及 behavior / conditions；Candidate 可带 engineering_risks、history_matches、scope_key、conditions、material_change。EvidenceRef 可同时附 quote、pointer 与 interpretation；引用有效不等于解释正确。详见[字段语义与示例](CANDIDATE_RISKS.md)。

本文面向插件集成与开发者。日常使用可直接在 Codex 对话中提出需求，见[决策卡指南](DECISION_GUIDANCE.md)。BuildChoice 通过 MCP 提供决策引导、项目记忆、实现关联、行为验证及文件证据接口。

## 连接与可用工具

安装器绑定目标工作区、Python 和运行时。启用原生设置与决策卡时提供 20 个工具：

| 分组 | 工具 |
|---|---|
| 设置 | buildchoice_settings_read、buildchoice_settings_update、buildchoice_settings_status |
| 文件证据与审计 | buildchoice_audit_start、buildchoice_audit_read、buildchoice_audit_decision、buildchoice_audit_report |
| 决策 | buildchoice_screen_candidates、buildchoice_card_activate、buildchoice_decision_status、buildchoice_decision_prepare_revision |
| 上下文与文档 | buildchoice_context、buildchoice_reply_interpret、buildchoice_record_instruction、buildchoice_decision_document |
| 实现与验证 | buildchoice_link_implementation、buildchoice_acceptance_prepare、buildchoice_verify_decision |
| 项目记忆 | buildchoice_memory、buildchoice_memory_manage |

决策卡关闭时隐藏决策写入、实现关联、验收/验证和记忆工具，保留 8 个工具；完全关闭时仅保留设置与决策状态，共 4 个。工具列表变更会发送通知，调用时仍执行开关校验。

会话句柄来自实际 UserPromptSubmit Hook。创建或访问可信任务时须传入当前有效句柄；自行填写 session_id 或复述“用户已同意”不能建立可信确认。工具调用不授予文件、网络或命令执行许可。

## 读取文件证据

默认使用 `buildchoice_context(session_handle, query="", paths=[], task_id=null, since=null, max_chars=12000)`：一次返回当前聊天决策、项目记忆、来源与字面变化。paths 最多 20 个项目相对路径，读取实际文件并复用当前有效来源，无需额外 audit_start/read；max_chars 为 2000–50000。检查 omitted / content_truncated，截断部分不视为已返回。since 需是同项目、同聊天的 snapshot_id；快照最多保留 100 份。

context 返回已答、待答、暂缓及恢复建议，查询不会创建确认、激活卡片或续期。默认包含来源待复核的记忆并标 needs_review，不包含已归档或遗忘项；跨聊天只共享项目参考。`changes` 比较文件哈希、决策和记忆状态，business_impact=requires_llm_assessment。

PostToolUse 上下文和 buildchoice_decision_status.observed_reads 也提供 source_id、路径、范围、文件哈希和 current。origin=hook_file_read 的正文不保存；服务端从仍匹配哈希的文件重建已返回范围。部分读取只允许范围内 quote，整文件记录才能使用 JSON pointer。需要独立审计报告时可显式创建来源收集会话：

~~~json
{"title":"小票保存规则","task":"核对已确认保存流程的相关资料"}
~~~

调用 buildchoice_audit_start，取得返回的会话 id，再调用 buildchoice_audit_read：

~~~json
{"session":"audit-...","path":"examples/receipt_review/receipt.json"}
~~~

该路径是仓库内示例；实际集成应换成绑定项目内的文件。读取器返回 id、content、locator、digest、reused 和读取时间。同会话、同路径、同文件版本重复读取复用来源；context 使用 source_id 字段。引用使用返回的来源编号，以及 JSON pointer 或精确 quote：

~~~json
{"source_id":"src-...","pointer":"/amount"}
~~~

来源收集会话的 task 是调用方说明，不是用户授权。文件读取与引用绑定可以证明内容、路径和哈希，不证明业务解释正确。

INSPECT 优先复用当前聊天的有效读取记录；单纯声明“已读”无效，新读取或文件变化会触发相关筛选缓存失效。支持工具、隐私保存与边界见[读取观察](PROJECT_READS.md)。

## 审计记录

使用 buildchoice_audit_decision(session, title, value, refs, impact?, rationale?) 登记引用，用 buildchoice_audit_report(session) 获取 report 与 markdown。引用在 pointer 与 quote 中选择一项，必须来自当前来源收集会话。

这些记录与 V3 的用户确认分别保存，不生成可信用户选择。报告中的 linked 表示字面值匹配，attention 表示缺失、变化或待核对，reviewed 表示已有复核意见；均不等于行为测试通过。

## 项目决策记忆

buildchoice_memory(query="", include_archived=false, session_handle) 需要当前有效 Hook 句柄，返回 memory.v1、最多 30 条参考/规则、确认来源、生命周期、冲突、total_matches、truncated、编号管理命令和本轮 management_request（没有真实管理指令时为 null）。查询不续期，也不创建确认。

buildchoice_memory_manage(memory_id, revision, session_handle, action="promote") 支持 promote / unpin / forget / restore；仅本轮 Hook 登记的唯一目标、动作和当前版本可以修改。真实自然语言已明确授权时无需二次确认；目标或意图不清返回 memory_status=clarification_required 与原因，不写管理事件。有效请求返回 applied、原范围与 replayed；重复请求不追加事件。带编号的完整命令由 Hook 直接处理。见[决策记忆](DECISION_MEMORY.md)。

Decision 可包含记忆匹配来源。project_rule_reused 不等于本任务的用户确认，不能直接用来创建仅接受本任务确认的验收集合。状态查询会重新核对复用规则的有效性。

候选的 memory_intent 为 reuse / change / uncertain，缺省 uncertain。仅核实需求未变且范围一致时使用 reuse。decision_key 是项目内稳定的决定标识，option_key 是稳定的选项标识，均为小写字母开头的 2–120 位字母、数字、点、下划线或连字符。显示字段和 A/B 排序可变，稳定键保持同一含义；显式 value 改变仍重新确认。未提供键的候选按字段、取值及选项后果匹配。匹配返回 PROJECT_MEMORY_RULE、project_rule_reused 和原确认来源。

## 决策引导接口

- `buildchoice_screen_candidates(request)`：接收 LLM 的 ASK_NOW / INSPECT / DEFER / PROCEED 建议，独立核对字段、来源及状态，附带 Agent 声明的覆盖依据；按 task_id + idempotency_key 防止重复登记。

工具列表直接提供 Candidate 字段和枚举 Schema。最小候选需要 candidate_id、field、category、question、impact、options 和 suggested_action；其他说明可按需提供。请求提供 task_text、next_step、candidates、session_handle 和 idempotency_key，不填写 phase。省略时程序只记录 unspecified，不推断开发阶段，也不影响分流；已有 before_implementation / during_implementation 调用仍兼容，显式非法值仍拒绝。priority=0..100 只用于调用方声明的排序，allow_defer 由调用方指定。错误返回紧凑字段路径与预期类型。响应同时保留 suggested_action 和 validation_status；来源失效时 status=INSPECT，不把文件变化解释为撤销用户选择。

筛选的任务/句柄绑定、候选、事件及缓存响应在单一写事务中提交，失败整体回滚。缓存只在所引用文件、未读资源和决定/确认/覆盖快照仍匹配时重放；过期或旧格式缓存返回 `CACHED_SCREEN_STALE`，执行中输入变化返回 `SCREEN_INPUT_CHANGED_DURING_EVALUATION`。前者需读取当前来源/状态后换新键筛选，后者未提交该请求的写入。新筛选的语义指纹不包含连接句柄或重复的 task_id，但先校验当前会话归属；改变候选等语义输入仍拒绝复用同一键。
- `buildchoice_card_activate(task_id, decision_id, revision, idempotency_key, session_handle)`：同会话最多激活一张待答卡，返回固定文本与 delivery_status=not_observed；重复激活同一卡片即使换键也不续期或重复写激活事件。
- `buildchoice_decision_status(task_id?, session_handle?)`：读取开关、未决项和实际确认历史。可信任务需要当前 Hook 句柄，不能只传 Agent 自报的会话 ID。
- `buildchoice_decision_prepare_revision(task_id, decision_id, revision, candidate, reason, session_handle)`：追加新版本，清除旧卡激活状态，新版本必须重新得到明确选择。

直接解析当前卡片的明确字母、序号、完整名称和推荐表达，记录 user_message_observed。复杂但明确的回复可调用 `buildchoice_reply_interpret(task_id, decision_id, revision, choice_id, quote, reason, session_handle)`：quote 必须在本轮真实消息中，冻结的卡片和当前版本须一致且未过期，返回 llm_interpreted_user_reply、semantic_verified_by_program=false。该工具记录 LLM 对真实回复的解释，不将语义判断标成程序核验结果；无原消息、换选项版本或跨聊天均拒绝。问句、否定、新条件与含糊表达由 LLM 先澄清。

`processing` 返回 duplicate、already_answered 和 previous_state。同任务相同候选换键重筛时保留当前确认或待答卡；重复候选不会创建第二份确认。暂缓项由上下文返回，不由程序自动决定重新询问。

## 决策文档

用户已明确指定或修改选择时，使用 `buildchoice_record_instruction(request)`，无需先发卡。request 包含本轮完整 user_message、精确 quote、解释 reason、session_handle、idempotency_key 和 expected_revision。新决定使用 expected_revision=0，并提供 decision：decision_key、field 和单个 choice（label/value 必填），scope_key/conditions 可指定范围。修订额外提供 decision_id 和当前 expected_revision；相同取值、行为与范围保留版本。再次确认现有决定时省略 decision/choice_id；回答已有提案可传 choice_id。工具 Schema 提供完整字段约束。

程序核对真实消息哈希、引用、归属、当前版本和幂等性，来源单独记为 llm_interpreted_user_instruction，semantic_verified_by_program=false。业务含义由 LLM 判断；问句、假设、否定及他人引语不能因为引用真实就视作决定。不会自动升级为长期规则或授予执行权限。原卡片回复接口继续要求实际待答卡，不接受伪造卡片交付。

账本与文档采用可恢复同步：先在单一事务中保存选择和文档待办，再原子替换生成文件。recorded=true 表示账本已提交，document.status=synchronized 才表示文件同步完成；pending 保留补写待办，重试原请求或调用 decision_document(write=true) 可恢复，不重复创建版本。旧回执带 latest_revision/current，不会恢复旧选择。默认生成 BUILDCHOICE_DECISIONS.md；同名手写文件保留，另选 .generated.md 等文件并返回路径。context.document 显示当前同步状态。

`buildchoice_decision_document(session_handle, task_id=null, include_archived=false, write=false, path="BUILDCHOICE_DECISIONS.md")` 返回 Markdown 与结构化决策、范围、来源和字面修订差异。默认展示项目当前参考与当前聊天任务；task_id 需属于当前聊天。默认预览，write=true 才原子写入项目 Markdown，路径的父目录须已存在。

指令记账建立的规范生成文件汇总项目当前已确认记录；向该路径写入时补齐最新投影。包含历史或仅单个任务的导出需另选路径，避免覆盖项目总记录。待办仍从 context 查询。新聊天可读取项目记忆和生成文档，不可直接修订其他聊天的任务；跨聊天参考不会自动成为本聊天的新授权。

只能覆盖带 BuildChoice 生成标记的文档；已有手写文件、私有路径、链接及越界路径拒绝。写文档不改变账本或规则。当前来源待复核项仍展示原选择，归档/遗忘/被替代项默认隐藏。详见[上下文与恢复](CONTEXT_WORKFLOW.md)。

## 决定与实现关联

`buildchoice_link_implementation(task_id, decision_id, revision, path, note, start_line?, end_line?, session_handle?)` 是可选接口，将真实 UTF-8 文件关联到当前 Hook 已确认的决定版本；未确认、Agent 自报及仅项目规则复用不能建立正式关联。path 为相对路径，note 说明关系，行号可省略，最大 256 KiB。拒绝越界、私有、链接路径、无效行号、过期版本和跨会话写入。无需每次开发调用。

服务端读取实际文件并保存 SHA256；不执行 Git，不修改文件，不存整段代码快照。同一决定版本/文件/行号重复登记相同内容时不重复写事件；内容或说明变化保留新事件。每任务最多 100 个关联。

返回 provenance=agent_reported_implementation、does_not_prove_correctness=true，并保存原 confirmation_id。该登记不建立用户确认，也不证明实现符合选择。`buildchoice_decision_status` 的 implementations 返回关联、当前 file_status 和 needs_recheck；决定版本变化、文件变化或不可读均提示复核。旧记录保留，关联本身不触发验证。

## 可选验收与验证

buildchoice_acceptance_prepare 和 buildchoice_verify_decision 是按需实验接口，仅在用户明确要求时使用。默认开发使用 Codex 原生测试，专用测试采集器由显式 CLI 启动；MCP 不自动执行项目命令。

## 覆盖记录与设置

`buildchoice_screen_candidates` 的 request 可带 coverage 数组（最多六项）：dimension、status、reason，可选 evidence_refs 与 candidate_ids。维度与形状见 [Schema](contracts/decision-v3.schema.json)。重复维度或未知候选 ID 会拒绝；未提交 coverage 时返回 reported=false。

响应 coverage 含 provenance=agent_declared、entries、reported 和 does_not_establish_completeness=true。每项独立返回 source_status 与 source_ids。该记录写入 V3 事件，任务状态返回最新一轮；不触发额外推理或参与分流。即使 resolved 引用了真实文件，也仍需判断约束的适用性。

原生设置工具为 `buildchoice_settings_read`、`buildchoice_settings_update`、`buildchoice_settings_status`。mode 支持 Prompt 优先 / 完全关闭，decision_guidance 支持关闭 / 试用。
