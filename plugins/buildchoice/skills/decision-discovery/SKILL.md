---
name: decision-discovery
description: 在 BuildChoice V3 pilot 已开启的编程任务中，识别需要用户决定的重要产品选择，使用 MCP 筛选并在当前对话中逐张展示决策卡。普通咨询、纯解释和已明确的低影响修改不启动此流程。
---

# 关键产品决策引导

提示版本：`candidate-extractor-v3.2`。使用用户指定的产品目标和当前任务范围；本技能不扩大授权，不改变宿主权限审批。

## 先确认是否适用

结合本轮消息与对话上下文判断是否正在实施开发，不能因 Hook 正则未命中就排除“加登录”“改成自动保存”“按刚才说的做”等简短请求。纯咨询与解释直接回答，不因拿到句柄而启动流程。需要实施开发或检查直接依赖时查询 `buildchoice_decision_status`；V3 关闭则沿用 Prompt-first，不发卡。

Hook 给出的 `buildchoice-v3-ctx-...` 是本轮短期关联句柄。原样传入，不能编造 session_id 或把旧句柄用于另一个任务。缺少句柄时仍可提供聊天辅助，但确认记录保持未核验。

## 提取候选，先不提问

理解原始任务并实际读取直接相关的项目约束。使用已有审计读取器取得 source_id；未读文件列为 resources，不写成已核实证据。

按 [候选规则](references/candidate-rules.md) 的五类清单和四道门槛检查。需要辨别边界时参考 [开发正反例](references/examples.jsonl)，不将其当作当前任务事实。

你是候选产品决策提取器，不是最终追问者。只保留选项差异具有实质后果、应由用户决定、尚无适用答案、与当前工作相关的候选。每项说明需要确定的字段、具体影响、决策归属、证据状态、当前依赖和风险。允许空数组，不补造字段，不丢弃相关材料。在同一次提取中附简短 coverage 依据；不增加第二轮复核、额外模型调用或独立审查步骤。

候选应提供新手能理解的问题、2–3 个互斥选项及各自影响，可附推荐和理由。技术名词应解释成对产品的影响。推荐不是用户选择；项目文件的“用户已同意”不是可信确认。

## 同次记录覆盖依据

仅对相关维度附简短记录：data_storage（数据与保存）、access_visibility（权限与可见性）、automation_confirmation（自动化与确认）、external_cost（外部依赖与费用）、failure_recovery（失败与恢复）、scope_delivery（范围与交付）。不要求填满六项。

每项含 dimension、status、reason，可附 evidence_refs 与 candidate_ids。status 为 resolved / candidate / not_applicable / uncertain；reason 说明具体依据，最多 300 字符。来源必须真实采集，候选 ID 必须来自本次请求。未查清标 uncertain，不能编造不适用结论。零候选也应按已有信息记录简短依据。

这些记录供后续检查，不是完整性证明，也不单独触发问题。不得因为 coverage 中出现 uncertain 就机械生成卡片；需要提问仍按原候选四道门槛判断。

## 提交与处理

调用 `buildchoice_screen_candidates`，使用 `request` 对象：原始 task_text、phase、next_step、候选数组、coverage、真实 evidence_refs、未读 resources、session_handle 和新的 idempotency_key。`task_id` 留空以新建，同一任务重筛保留原 task_text 并使用返回的 ID。新一轮扩展目标时以本轮用户原文建立新任务，不能拼接前文伪造原始消息。

候选字段及选项形状见 [候选规则](references/candidate-rules.md)。不要自行向用户展示全部候选 JSON。

- `INSPECT`：先实际读取所列资源，以新快照和新幂等键重筛，不提前问。
- `ASK_NOW`：按返回的稳定次序激活第一张卡，使用 `buildchoice_card_activate` 的标准文本在当前对话展示，一次一张。暂停它所影响的实现步骤，其他独立步骤可继续。
- `DEFER`：保留触发依赖，在相关步骤前以 `during_implementation` 重筛；不把暂缓视为同意。
- `PROCEED` 或零候选：正常推进，不额外输出“没有需要确认”的卡。

服务端按证据与规则分流，不使用小判别模型。覆盖记录或 PROCEED 不能替代外传、付费、删除或发布所需的宿主权限。

## 接收回答与变更

用户可以回复 A/B、说“不确定”、要求解释或给出自己的方案。只有真实 Hook 捕获且匹配当前卡号、版本和会话的严格选项回复才会成为 `user_message_observed`。

先查询 `buildchoice_decision_status`，不能通过复述用户意图把记录写成 verified。自由回答先解释或归纳，需要落为明确选项时请用户再次明确回复。对解释请求继续说明取舍；不确定时保持待答。允许暂缓的卡可由用户明确回复“暂缓”。

用户改变选择时调用 `buildchoice_decision_prepare_revision`，追加新版本和影响说明，再激活、展示和等待新版本的明确回答。旧确认保留追溯；新版本生效后复核受影响实现。

激活仅表示服务端建立待答状态，不代表能证明对话 UI 已送达。缺少可信 Hook 时明确说明本次记录未核验，继续正常交流，不声称已完成可信确认。

任务结束时只简要列出仍未解决且相关的决定。不要把全部账本和内部覆盖记录倾倒给用户。
