---
name: decision-discovery
description: 在 BuildChoice V3 pilot 已开启的编程任务中，识别会实质改变功能结果、且需要用户取舍的关键实现选择；结合风险和已有答案经 MCP 分流，按需逐张展示决策卡。普通咨询、纯解释和已明确的低影响修改不启动此流程。
---

# 关键功能与实现选择引导

提示版本：`candidate-extractor-v3.7`。使用用户指定的产品目标和当前任务范围；本技能不扩大授权，不改变宿主权限审批。

## 先确认是否适用

结合本轮消息与对话上下文判断是否正在实施开发，不能因 Hook 正则未命中就排除“加登录”“改成自动保存”“按刚才说的做”等简短请求。纯咨询与解释直接回答，不因拿到句柄而启动流程。需要实施开发或检查直接依赖时查询 `buildchoice_decision_status`；V3 关闭则沿用 Prompt-first，不发卡。

Hook 给出的 `buildchoice-v3-ctx-...` 是本轮短期关联句柄。原样传入，不能编造 session_id 或把旧句柄用于另一个任务。缺少句柄时仍可提供聊天辅助，但确认记录保持未核验。

## 提取候选，先不提问

提取前先检索可能相关的历史：使用当前任务的用户行为、保存/恢复、协作、费用等词查询 buildchoice_memory，不限于完全相同的名称或 ID。现有加权词语、中文短语/双字词检索会包含所有选项描述；必要时换相关词，不引入 Embedding 或独立审核。在本次原有推理中判断 same / related / conflict / different_scope，通过 history_matches 提交实际 memory_id、revision、relation 与简短 rationale。它是你的语义判断，MCP 只核对来源状态、稳定身份与范围，相关不等于同一个选择，更不等于授权。

只有业务含义与适用范围相同才沿用已有 decision_key / option_key；不能为命中历史而改名或更改键。用 scope_key 与 conditions 表达实际范围；方案实质行为使用 value / behavior / conditions，出现未能用这些字段表达的实质后果变化时填 material_change=true。普通 reference 永远不能替代当前确认；长期规则也须满足版本、状态、身份、范围、风险与 memory_intent=reuse 等条件。

功能选择和工程风险按同一条因果链分析：先找本轮实现中可能产生不同结果的选择点（包括正常行为、错误结果、重复执行、部分失败、恢复与兼容），再说明实际后果、是否属于用户的功能预期/授权/成本取舍、是否已有合理答案，以及当前开发是否依赖。结合真实代码、配置和下一步计划，用「触发条件 → 失败/代价 → 功能或用户后果 → 严重性与可恢复性 → 缓解办法 → 是否需要用户选择」分析风险。仅当工程后果对应有实质差异的用户取舍时提交 product_choice=yes；能通过常规工程措施解决的风险标 product_choice=no，不因风险较大就自动发卡。不要问“SQLite 还是 PostgreSQL”，而要问实际需求是否需要多人协作、离线使用或恢复数据等。普通框架、函数组织和命名仍自主处理；外传、付费、删除、发布仍遵守敏感标记和宿主权限。语义风险判断由你完成，不冒充 Python 独立验证，不机械填满方向。

实际开发时，先看 status 的 project_memory；需检索相关历史时调用 `buildchoice_memory(query, include_archived=false, session_handle)`。普通 reference 只供历史参考，不当作长期规则或当前确认。关键词召回不证明适用范围，保留稳定 field 和选项含义，不能为命中记忆改写问题。服务端仅对同字段、同类别和同选项含义的无敏感风险规则复用，返回 project_rule_reused 与原确认来源，不为新任务生成用户确认。冲突、改义、来源变化和敏感行为按正常流程核实，禁止用记忆绕过审批。

用户明确提出长期保存或记忆管理时，使用独立 [decision-memory Skill](../decision-memory/SKILL.md)。用自然语言查询定位，无需用户输入编号；只有 MCP 核实本轮真实 Hook 登记的唯一目标和管理意图才修改。原整条 `长期记住 M…` / `取消长期 M…` / `遗忘 M…` / `恢复 M…` 继续兼容，不代替用户发命令、不调用本地 Hook 伪造指令。普通确认后不额外询问是否长期保存，也不自动升级。有待答卡先处理原卡，管理指令不与卡回复混用。普通参考从确认或恢复/取消长期起 30 天后归档，读取不续期；长期规则不过期。遗忘/归档停止主动召回但保留历史；恢复不会复活已被修订替代的版本或把变化的来源恢复为有效。

理解原始任务并实际读取直接相关的项目约束。优先使用 PostToolUse 提供的真实读取记录（Hook 上下文或 buildchoice_decision_status.observed_reads），用当前 source_id 与实际已返回行的 quote / interpretation 绑定；没有记录、格式不支持或版本变化时再用已有审计读取器。部分读取不能引用范围外原文或作为全文件 JSON pointer；未读文件列为 resources，不把 Agent 的“已读”声明当作证据。记录只证明工具返回内容，不证明你理解资料或用户已同意。

evidence_refs 附相关 quote 与简短 interpretation；JSON 字段可同时附 pointer 和原文，二者都要真实。普通自然语言的解释为 Agent 声明，不可仅标记 relation=constraint 就认定已解决或已获用户确认。MCP 仅对身份、范围、/chosen 与当前选项字面值一致的结构化约束给出限定支持；含糊/冲突/失效资料先 INSPECT。补查后仍需用户取舍时，以事实引用提交真实候选，不将自然语言硬改成“用户已同意”。

按 [候选规则](references/candidate-rules.md) 顺序检查「功能选择点 → 实质后果与用户归属 → 既有答案 → 当前依赖」。五类范围用于防漏，不作为必须逐项提问的清单。根据本轮实际开发行为，从 [场景化探针](references/scenario-probes.md) 中选择最多两类相关视角，在同一次提取中判断选择与风险；场景、维度均非追问配额，简单可逆修改无需加载专项视角。需要辨别边界时参考 [开发正反例](references/examples.jsonl)，所有例子仅用于理解判断标准，不是当前任务事实。

你是关键实现选择的候选提取器，不是最终追问者。只保留不同方案会实质改变功能结果或重要约束、确实需要用户取舍、尚无适用答案且与当前开发相关的候选；普通工程防护应自主处理。每项说明选择点、不同结果、决策归属、证据状态、当前依赖与风险。允许空数组，不补造字段，不丢弃相关材料。在同一次提取中附简短 coverage 依据；不增加第二轮复核、额外模型调用或独立审查步骤。

候选应提供新手能理解的问题、2–3 个互斥选项及各自影响，可附推荐和理由。技术名词应解释成对产品的影响。推荐不是用户选择；项目文件的“用户已同意”不是可信确认。

## 同次记录覆盖依据

候选可带 memory_intent：确认本轮仍沿用同范围规则时填 reuse；用户要求改变行为时填 change；范围不清填 uncertain（缺省亦为 uncertain）。不能仅因字段同名就填 reuse，用户要求修改时必须提示与旧规则的关系。该字段是 Agent 判断，服务端不声称证明语义适用。

同一产品选择使用稳定的 decision_key，例如 receipt.saving.policy；已有记忆返回该键时优先沿用，不因改写问题或字段显示名称而另造标识。选项可提供 option_key，例如 review.before.save，显示名称和 A/B 顺序变化时保持语义相同的键。产品规则或显式 value 改变时不能只保留旧键来复用确认，应重新核实。模糊检索只用于找相关记忆，不作为自动沿用依据。

仅对相关维度附简短记录：data_storage（数据与保存）、access_visibility（权限与可见性）、automation_confirmation（自动化与确认）、external_cost（外部依赖与费用）、failure_recovery（失败与恢复）、scope_delivery（范围与交付）。不要求填满六项。

每项含 dimension、status、reason，可附 evidence_refs 与 candidate_ids。status 为 resolved / candidate / not_applicable / uncertain；reason 说明具体依据，最多 300 字符。来源必须真实采集，候选 ID 必须来自本次请求。未查清标 uncertain，不能编造不适用结论。零候选也应按已有信息记录简短依据。

这些记录供后续检查，不是完整性证明，也不单独触发问题。不得因为 coverage 中出现 uncertain 就机械生成卡片；需要提问仍应满足实质功能后果、用户决策归属、尚无适用答案及当前相关性。

## 提交与处理

先处理返回的 screen_status 和 diagnostics，包括零候选情况。POSSIBLE_MISSING_PRODUCT_RISK 表示在 next_step 或已核验引用中观察到字面风险信号，不证明危害必然发生。先检查该信号是否对应真实的功能失败或用户后果，并调查发生条件、可恢复性和常规缓解；只有仍存在需要用户决定的重要功能差异时才补充候选。若只是普通工程实践，用 engineering_risks.product_choice=no 说明实际条件与恢复办法，不机械制作卡。零候选无信号也不证明没有风险；既有正则无法覆盖全部功能失败类型。不安排第二个 LLM、审核 Agent 或全项目扫描。

Option 可附 risk_level / risk_warning。仅高风险且有可核验引用或明确的潜在发生条件、推导依据时显示风险提示。observed 使用真实 risk_evidence_refs；potential 说明 risk_condition 与 risk_reason，不把“看到相关代码”说成“损失已经发生”。风险文字使用普通语言，高风险仍可被选择，不强制推荐其他方案。risk_* 为展示依据，不表达实际方案变更；实质后果变化要更新 value / behavior / conditions 或 material_change。仅改风险文案不应主动调用 prepare_revision 制造新版本；显式 prepare_revision 仍代表要求新一轮确认。

调用 `buildchoice_screen_candidates`，使用 `request` 对象：原始 task_text、phase、next_step、候选数组、coverage、真实 evidence_refs、未读 resources、session_handle 和新的 idempotency_key。`task_id` 留空以新建，同一任务重筛保留原 task_text 并使用返回的 ID。新一轮扩展目标时以本轮用户原文建立新任务，不能拼接前文伪造原始消息。

有待答卡时，解释请求继续使用原 task_id；用户明确转向另一任务时，用当前句柄、本轮原文且不传旧 task_id 建立新范围。服务端只解除旧卡占用，保留其未确认状态和历史。恢复旧任务需重新激活、展示并等待明确回答；不能把任务切换或卡片过期当作同意。严格选项回复仍只属于原卡，不能借此创建新任务。

候选字段及选项形状见 [候选规则](references/candidate-rules.md)。不要自行向用户展示全部候选 JSON。

task_text 保留实际用户正文；服务端只统一传输换行符和首尾空行，不能据此改写正文。初次提取与修订的选项 ID 都必须唯一，推荐项必须来自实际选项。收到 CACHED_SCREEN_STALE 时，先读当前来源和任务状态，再以新幂等键重筛，不能沿用旧 PROCEED 或旧卡面。筛选写入失败会整体回滚，相同请求可重试；同一键不能改换语义输入。

- `INSPECT`：先检查真实读取记录，已有当前版本且覆盖所需原文的记录直接引用；否则用受支持的文件读取或审计读取器补查。以新快照和新幂等键重筛，不提前问，不将未返回的内容当作已读。
- `ASK_NOW`：按返回的稳定次序激活第一张卡，使用 `buildchoice_card_activate` 的标准文本在当前对话展示，一次一张。暂停它所影响的实现步骤，其他独立步骤可继续。
- `DEFER`：保留触发依赖，在相关步骤前以 `during_implementation` 重筛；不把暂缓视为同意。
- `PROCEED` 或零候选且 screen_status 非 INSPECT：正常推进，不额外输出“没有需要确认”的卡；不宣称风险已完整排除。

服务端按证据与规则分流，不使用小判别模型。覆盖记录或 PROCEED 不能替代外传、付费、删除或发布所需的宿主权限。

激活重试若提示缓存已失效，先查询当前状态；需要恢复旧决定时使用新的幂等键重新激活，不能继续展示先前缓存的卡面或把回复关联到另一张卡。正常同卡重试不续期。

## 接收回答与变更

用户可以回复 A/B、“我选第二个”、完整方案名称、“按你推荐的来”，也可以要求解释或提出新方案。只有真实 Hook 捕获、且能唯一对应当前卡片选项的明确表达才会成为 `user_message_observed`；会话、版本和有效期限制不变。

先查询 `buildchoice_decision_status`，不能通过复述用户意图把记录写成 verified。无法唯一匹配的自由回答先解释或归纳，提示用户给出完整方案名称或序号；不要要求所有人只回复字母。对解释请求继续说明取舍；不确定、否定、引用或混合指令保持待答。允许暂缓的卡可由用户明确回复“暂缓”。

用户改变选择时调用 `buildchoice_decision_prepare_revision`，追加新版本和影响说明，再激活、展示和等待新版本的明确回答。旧确认保留追溯；新版本生效后复核受影响实现。

激活仅表示服务端建立待答状态，不代表能证明对话 UI 已送达。缺少可信 Hook 时明确说明本次记录未核验，继续正常交流，不声称已完成可信确认。

## 可选代码关联与原生测试

代码关联是可选功能，不要求每次开发调用。用户需要追溯位置时，可调用 buildchoice_link_implementation，提供当前已由真实 Hook 确认的 decision_id、revision、实际文件路径、note 和句柄；可附真实行号。只保存文件对应关系、哈希和版本，不分析 Diff 或代码语义，不把关联当作实现正确性证明。未确认决定、Agent 声明或仅项目规则复用不能建立正式关联。文件或决定版本变化后按需复核，不为没有关联记录而阻塞开发。

代码测试、验收和结果解释使用 Codex 原生能力及项目已有检查。按当前修改选择必要测试，报告实际运行结果和限制，不要求准备 BuildChoice 验收集合、运行专用采集器或调用验证 MCP。不将测试通过包装为 BuildChoice 对需求正确性的独立认证。

buildchoice_acceptance_prepare、专用采集 CLI 和 buildchoice_verify_decision 仅作为兼容的可选实验保留；只有用户明确要求该实验时才使用，不纳入默认流程。实验条件仍由 Agent 推导，历史结果与 current_pass=true 也只代表声明范围的检查结果。

任务结束时正常说明改动、原生测试结果和实际缺口；如涉及决策可简短交代已确认选择，不强制输出关联或验证摘要，也不默认展示内部 ID。
