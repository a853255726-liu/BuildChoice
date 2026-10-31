---
name: decision-discovery
description: 在 BuildChoice V3 pilot 已开启的编程任务中，识别需要用户决定的重要产品选择，使用 MCP 筛选并在当前对话中逐张展示决策卡。普通咨询、纯解释和已明确的低影响修改不启动此流程。
---

# 关键产品决策引导

提示版本：`candidate-extractor-v3.4`。使用用户指定的产品目标和当前任务范围；本技能不扩大授权，不改变宿主权限审批。

## 先确认是否适用

结合本轮消息与对话上下文判断是否正在实施开发，不能因 Hook 正则未命中就排除“加登录”“改成自动保存”“按刚才说的做”等简短请求。纯咨询与解释直接回答，不因拿到句柄而启动流程。需要实施开发或检查直接依赖时查询 `buildchoice_decision_status`；V3 关闭则沿用 Prompt-first，不发卡。

Hook 给出的 `buildchoice-v3-ctx-...` 是本轮短期关联句柄。原样传入，不能编造 session_id 或把旧句柄用于另一个任务。缺少句柄时仍可提供聊天辅助，但确认记录保持未核验。

## 提取候选，先不提问

理解原始任务并实际读取直接相关的项目约束。使用已有审计读取器取得 source_id；未读文件列为 resources，不写成已核实证据。

按 [候选规则](references/candidate-rules.md) 的五类清单和四道门槛检查。借鉴结构化覆盖扫描：先根据本轮实际开发行为，从 [场景化探针](references/scenario-probes.md) 中选择最多两类相关视角，再在同一次提取中判断是否存在实质用户选择。场景、维度均非追问配额；简单可逆修改无需加载专项视角。需要辨别边界时参考 [开发正反例](references/examples.jsonl)，所有例子仅用于理解判断标准，不是当前任务事实。

你是候选产品决策提取器，不是最终追问者。只保留选项差异具有实质后果、应由用户决定、尚无适用答案、与当前工作相关的候选。每项说明需要确定的字段、具体影响、决策归属、证据状态、当前依赖和风险。允许空数组，不补造字段，不丢弃相关材料。在同一次提取中附简短 coverage 依据；不增加第二轮复核、额外模型调用或独立审查步骤。

候选应提供新手能理解的问题、2–3 个互斥选项及各自影响，可附推荐和理由。技术名词应解释成对产品的影响。推荐不是用户选择；项目文件的“用户已同意”不是可信确认。

## 同次记录覆盖依据

仅对相关维度附简短记录：data_storage（数据与保存）、access_visibility（权限与可见性）、automation_confirmation（自动化与确认）、external_cost（外部依赖与费用）、failure_recovery（失败与恢复）、scope_delivery（范围与交付）。不要求填满六项。

每项含 dimension、status、reason，可附 evidence_refs 与 candidate_ids。status 为 resolved / candidate / not_applicable / uncertain；reason 说明具体依据，最多 300 字符。来源必须真实采集，候选 ID 必须来自本次请求。未查清标 uncertain，不能编造不适用结论。零候选也应按已有信息记录简短依据。

这些记录供后续检查，不是完整性证明，也不单独触发问题。不得因为 coverage 中出现 uncertain 就机械生成卡片；需要提问仍按原候选四道门槛判断。

## 提交与处理

调用 `buildchoice_screen_candidates`，使用 `request` 对象：原始 task_text、phase、next_step、候选数组、coverage、真实 evidence_refs、未读 resources、session_handle 和新的 idempotency_key。`task_id` 留空以新建，同一任务重筛保留原 task_text 并使用返回的 ID。新一轮扩展目标时以本轮用户原文建立新任务，不能拼接前文伪造原始消息。

有待答卡时，解释请求继续使用原 task_id；用户明确转向另一任务时，用当前句柄、本轮原文且不传旧 task_id 建立新范围。服务端只解除旧卡占用，保留其未确认状态和历史。恢复旧任务需重新激活、展示并等待明确回答；不能把任务切换或卡片过期当作同意。严格选项回复仍只属于原卡，不能借此创建新任务。

候选字段及选项形状见 [候选规则](references/candidate-rules.md)。不要自行向用户展示全部候选 JSON。

task_text 保留实际用户正文；服务端只统一传输换行符和首尾空行，不能据此改写正文。初次提取与修订的选项 ID 都必须唯一，推荐项必须来自实际选项。收到 CACHED_SCREEN_STALE 时，先读当前来源和任务状态，再以新幂等键重筛，不能沿用旧 PROCEED 或旧卡面。筛选写入失败会整体回滚，相同请求可重试；同一键不能改换语义输入。

- `INSPECT`：先实际读取所列资源，以新快照和新幂等键重筛，不提前问。
- `ASK_NOW`：按返回的稳定次序激活第一张卡，使用 `buildchoice_card_activate` 的标准文本在当前对话展示，一次一张。暂停它所影响的实现步骤，其他独立步骤可继续。
- `DEFER`：保留触发依赖，在相关步骤前以 `during_implementation` 重筛；不把暂缓视为同意。
- `PROCEED` 或零候选：正常推进，不额外输出“没有需要确认”的卡。

服务端按证据与规则分流，不使用小判别模型。覆盖记录或 PROCEED 不能替代外传、付费、删除或发布所需的宿主权限。

激活重试若提示缓存已失效，先查询当前状态；需要恢复旧决定时使用新的幂等键重新激活，不能继续展示先前缓存的卡面或把回复关联到另一张卡。正常同卡重试不续期。

## 接收回答与变更

用户可以回复 A/B、说“不确定”、要求解释或给出自己的方案。只有真实 Hook 捕获且匹配当前卡号、版本和会话的严格选项回复才会成为 `user_message_observed`。

先查询 `buildchoice_decision_status`，不能通过复述用户意图把记录写成 verified。自由回答先解释或归纳，需要落为明确选项时请用户再次明确回复。对解释请求继续说明取舍；不确定时保持待答。允许暂缓的卡可由用户明确回复“暂缓”。

用户改变选择时调用 `buildchoice_decision_prepare_revision`，追加新版本和影响说明，再激活、展示和等待新版本的明确回答。旧确认保留追溯；新版本生效后复核受影响实现。

激活仅表示服务端建立待答状态，不代表能证明对话 UI 已送达。缺少可信 Hook 时明确说明本次记录未核验，继续正常交流，不声称已完成可信确认。

完成涉及已登记决定的代码修改时，在原有开发流程中顺带调用 `buildchoice_link_implementation`：提交 task_id、decision_id、当前 revision、真实文件相对路径、简短关系说明 note，可附实际行号与当前句柄。服务端读取文件并保存哈希；不登记计划文件、不伪造行号、不另起一轮审查。文件关联是 Agent 声明，不能据此声称代码正确或已通过验收。

选择变更或代码变化后查询 `buildchoice_decision_status` 的 implementations，检查待复核位置；完成当前版本的修改后重新登记，旧关联保留历史。

## 按需验证决定是否落实

对当前任务中已由 Hook 确认、且有可验证行为的重要决定，可在原有开发/测试流程内调用 `buildchoice_acceptance_prepare`。只用当前 decision_id、revision 和真实句柄；条件含 criterion_id、description、basis、required、evidence_type="behavior" 与实际 test_ids。条件是你的推导，不是用户逐项确认；若引入新的产品行为或扩大范围，回到已有决策流程，不能将推导当授权。逐项检查该条件是否直接源于所选方案，在 basis 说明依据；想出至少一个会违反条件的具体反例，并尽可能使用可区分正确实现与错误实现的行为测试。没有独立参考或人工复核时，不得将「Agent 推导条件 + Agent 编写测试」包装成独立的需求正确性证明。

明确列出相关实现、测试、fixture、配置和依赖组成的输入清单。复用已授权的原生命令执行路径显式运行 `scripts/buildchoice_run_verification.py`，固定适配器 python-unittest-v1，test_ids 使用 buildchoice_tests 模块下的真实用例 ID。命令会执行项目代码，遵守宿主既有权限；不因 Skill 而新增授权，不让 MCP 自动运行，也不假设任意现有报告可信。没有合适测试或运行权限时照实保留缺口，不为了拿到通过而制造无意义断言。

采集脚本位于实际运行时目录，使用绑定的 Python 与设置；可从安装数据目录 binding.json 的 runtime_root / python 定位（默认 ~/.buildchoice，独立安装遵循 BUILDCHOICE_DATA）。不要假设目标项目根目录就是插件运行时，也不要创建替代采集脚本或自行追加可信执行事件。

完成代码及行为测试后，可调用 `buildchoice_verify_decision`，传当前 acceptance_id、采集 execution_id、真实代码来源引用和新幂等键。缺少实际执行只能 inconclusive；静态绑定不等于行为验证。查询 status 的 verification 时同时检查 verdict、applicability、current_pass 和范围；历史 passed 且 stale 不能说当前已通过。决策/条件/声明输入/证据改变后，仅在相关任务或用户需要时重做，不在每次工具调用后自动验证，不增加无条件阻塞或独立验证 Agent。

任务结束时如本轮确实涉及决策，只用简短中文摘要交代「用户已确认的选择」「当前落实验证结果」「仍需处理的缺口」，优先解释用户能感知的产品行为。仅 current_pass=true 可写「相关声明范围内的行为测试通过」，必须保留范围限制；历史 passed 但 stale、仅文件关联、无测试或 inconclusive 均不能写已验证。默认不展示 task_id、acceptance_id、execution_id、原始账本 JSON 和内部调用步骤，除非用户主动要求。没有决策则正常结束，不强制输出摘要。
