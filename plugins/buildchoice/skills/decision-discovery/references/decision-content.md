# 结构化决策内容

新候选使用 content_version=decision-content.v1。先生成数据，再让 screen_candidates 校验；通过后激活返回的固定模板。旧卡可接续，不为升级改写旧版本或要求用户重新确认。

## 提交与可选字段

请求外层按当前工具 Schema 提交 task_text、next_step、candidates、session_handle、idempotency_key，不填写 phase。阶段记录由程序处理，不影响业务判断。新候选使用 candidate_id、field、category、question、impact、2–3 个 options 和 suggested_action；每项选项含 id、label、tradeoff 和明确 risk_assessment。退休字段 needs_user_choice/current_dependency/relevance/engineering_detail/why_user_choice 不再提交。

候选还可带 evidence_refs、depends_on、priority、allow_defer、memory_intent、scope_key、conditions、material_change、engineering_risks 与 history_matches。引用使用 context 或真实读取器返回的 source_id，pointer 与 quote 可同时核对；interpretation 是 LLM 解释，不是用户授权。未读资料放请求 resources；不要编造来源。

category 为 business_rule / access_control / data_privacy / cost_external / scope / engineering。suggested_action 为 ASK_NOW / INSPECT / DEFER / PROCEED。priority 为0–100，数字越小越先展示，由你决定。

## 写什么

- question：只问一个选择，不混入“产品影响、推荐理由、可以讨论”等段落。
- label：短名称，不带 A/B、数字、Markdown 或“（推荐）”。id 和 recommended_option_id 分别表达编号与推荐。
- tradeoff：用户选择后具体会怎样，保留关键范围、限制和不同后果。不能把不同方案都写成同一句优点。
- impact：解释为什么值得用户选择，保存于详情；用户选择所必需的限制必须写入选项，不能仅藏在详情。
- recommendation_reason：有推荐时才填写，说明此方案相对其他方案更符合哪个真实需求。不要复述选项，也不要把两种方案都能满足的约束当作唯一推荐依据。不确定就不推荐。

单行纯文本的长度上限：question 90、label 32、tradeoff 140、impact 160、recommendation_reason 100、risk_warning 180、risk_condition 140、risk_reason 200 字符。超限应重新概括，保留行为、限制和风险；不能机械截断，也不能为变短删掉实质后果。程序只检测确切重复、格式与结构矛盾；改写同义句不能代替内容审阅。

## 每个选项明确风险评估状态

risk_assessment 为 {status, reason}；reason 简述本轮评估范围或尚缺什么，最多 200 字符，归属 agent_declared，不构成独立认证。

- not_assessed：尚未充分评估，不能写成“安全”或“没有风险”。如果缺失事实会影响当前选择，先 INSPECT；不为风险状态单独制造确认。
- no_specific_risk：在已说明的范围内没识别到具体风险，不证明绝对安全。不能同时填风险字段。
- risks_identified：填写 risk_level、risk_warning、risk_basis。严重性与是否需要产品取舍由你判断；程序不因风险标签自动发卡。

已识别风险无论 low/medium/high 都可展示，不能用“不是高风险”隐去实质后果。potential 必须有 risk_condition 和 risk_reason，表示触发条件与推断机制；observed 必须给当前资料真实 risk_evidence_refs。引用有效只证明原文存在，不证明你的风险解释正确。工程预防措施可以直接执行时，不硬改成用户产品选择。

## 示例：打开方式

以下只是内容形状示例，评估理由须由实际项目资料支持：

```json
{
  "content_version": "decision-content.v1",
  "candidate_id": "ui-surface",
  "field": "界面打开方式",
  "category": "scope",
  "question": "你希望怎样打开记账界面？",
  "impact": "影响日常启动方式和界面操作体验。",
  "suggested_action": "ASK_NOW",
  "options": [
    {"id":"A","label":"桌面窗口","tradeoff":"直接打开独立窗口操作。","risk_assessment":{"status":"not_assessed","reason":"尚未核对目标电脑的桌面组件与打包要求。"}},
    {"id":"B","label":"本机浏览器","tradeoff":"先启动本机服务，再用浏览器打开。","risk_assessment":{"status":"not_assessed","reason":"尚未核对服务绑定范围及启动要求。"}}
  ]
}
```

## 校验失败与展示

CONTENT_REPAIR_REQUIRED 返回 issues[].field/rule 和 next_action。按失败字段修正后用新幂等键重试；若约束无法在不丢失意义的前提下满足，说明具体限制，不展示另一张绕过校验的卡。引用不成立时先重读，不编造替代依据。不要重复调用完全相同的失败请求。

程序通过格式与来源校验不代表推荐合理、风险完整或用户已认可。presentation.native_request 原样交宿主；title 只有问题，选项由固定模板添加推荐和风险，宿主负责视觉编号。额外依据在 presentation.details，用户要求解释时再用自然语言说明，不默认复制到卡片前后。
