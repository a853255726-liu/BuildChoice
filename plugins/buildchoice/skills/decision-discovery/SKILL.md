---
name: decision-discovery
description: 在 BuildChoice 开发任务中识别重要产品取舍并保存可信决定；用户要求规划或核对产品体验、解释产品行为变化时，按任务启用场景预期、行为审阅及集中决策。咨询和低影响实现细节不发卡。
---

# 关键实现选择

提示版本：`candidate-extractor-v4.1`。你判断重要性、业务含义、资料适用性、语义等价及提问时机；程序核对结构、真实引用、归属、版本和状态。工具记录不授予宿主操作权限。

## 选择最短路径

实际开发或实施前检查时，按需用 `buildchoice_context(session_handle, query, paths)` 一次取得已有选择、待答项、项目记忆和直接相关资料。已有充分且有效的上下文可直接使用，不固定重复查询 status/memory，不先另开审计会话。检查 omitted/content_truncated，截断部分不能当成已读。新聊天先核对项目记忆和 document 同步状态。

先判断是否涉及重要产品取舍或已有决定的变更。输入字段来源、读取路径和既定技术前提等明确事实直接沿用，不逐条建立决定；用户明确要求将其保存为决定时再记录。对用户解释产品后果和保存结果，不援引内部 Skill 或工具流程作为产品依据。

- **用户已明确作出重要选择或修订已有决定**：用 `buildchoice_record_instruction`，不要先 screen、prepare_revision 或发卡。提交完整本轮 user_message（不含 Hook 上下文）、精确 quote、reason、句柄与幂等键。更新使用已有 decision_id/expected_revision 和稳定 decision_key，以一个 choice 的 label/value 完整表达行为与范围。重复确认同一决定时省略 decision/choice_id，沿用版本。不要手工改 Markdown 代替记账。
- **仍需用户选择**：提交候选 → 检查 validation_status → 激活可用的 ASK_NOW 卡并原样展示返回的 message。普通任务沿用单卡；启用产品体验任务后，适合共同处理的独立问题可用集中决策（每批最多 3 项）。只暂停该选择影响的步骤，其余工作继续。
- **回复已有卡**：Hook 已登记的直接沿用；明确对应原卡但仍待答时用 `buildchoice_reply_interpret`。过期或变更卡不能接受迟到的字母回复。新条件改走指令修订或澄清。
- **没有重要未决选择**：正常继续，不为留记录制造候选或工具调用。已答的不重复询问；暂缓项在你判断相关依赖将到达时再评估。

语义由你负责：疑问、否定、假设、他人引语及含糊范围不能仅因原话真实就当成决定。需要参数细节、待办恢复或处理文档 pending 时，读 [指令与回复记账](references/recording.md)。只有 recorded=true 才说明决定已保存；document.status=synchronized 才说明文档已同步。

## 候选与可选扩展

按 [候选规则](references/candidate-rules.md) 判断选择点、产品后果、用户归属、已有答案和当前时机；按需从 [场景探针](references/scenario-probes.md) 选择最多两类视角，不凑问题。需要例子时读 [正反例](references/examples.jsonl)。

`buildchoice_screen_candidates(request)` 的候选核心只有 candidate_id、field、category、question、impact、2–3 个 options 和 suggested_action；选项至少有 id/label/tradeoff。明确提交 ASK_NOW / INSPECT / DEFER / PROCEED，不再填写 needs_user_choice、current_dependency、relevance、engineering_detail 或 why_user_choice。request 使用原始 task_text、next_step、候选数组、真实句柄和新幂等键，不填阶段标签。

来源 evidence_refs、范围 scope_key/conditions、稳定 decision_key/option_key、行为 value/behavior、风险解释和工程后果都是按需扩展；不要仅为填满 Schema 生成它们。history_matches/memory_intent 仅用于确有历史复用需求时。引用有效不证明业务解释正确，相似检索也不构成授权。validation_status 描述程序核验，suggested_action 是你的业务建议；引用错误先修正事实，不把它理解为必须提问。

普通记忆只供参考。仅当你核对行为与范围相同，且当前长期规则有效时，明确提交 memory_intent=reuse 和 suggested_action=PROCEED；身份、来源或版本不匹配仍需补查，不让程序猜是否复用。

## 按需能力

用户要求规划/确认产品体验、解释产品行为变化、核对开发结果或明确开启流程时，读 [产品预期、行为审阅与集中决策](references/product-review.md)，使用日常工具中的四个正式产品入口按任务启用；已启用任务继续接续，直到完成或用户关闭。普通开发任务不强制生成场景或快照。业务含义仍由你判断，不新增独立 Agent 或分类器。

日常工具集已含上下文、候选、卡片、两种记账入口和文档补写。指令记账自动维护生成文档；有 pending 时重试原请求或 `buildchoice_decision_document(write=true)`，不直接改 SQLite。生成文件不可代替原消息授权。

独立审计、记忆管理、代码关联、提议修订和实验验证仅在确有需求时使用完整工具集。用户明确要求这些能力时，可切换原生设置“工具集：完整”，或执行 `python scripts/buildchoice_decisions.py full`；支持设置工具时也可调用 settings_update 的 tool_profile。切换只暴露入口，实际操作仍须满足原来的来源和权限约束。完成后可切回日常，不自动开启实验验证。

普通确认只形成项目参考；明确要求长期保存或管理时再使用 [decision-memory](../decision-memory/SKILL.md)。测试优先用 Codex 原生能力；不默认创建验收集合或独立认证，兼容实验接口只在用户明确要求时使用。
