# 候选与程序校验的边界

按四个步骤判断，不把模糊程度或风险标签直接当作追问理由：

1. **发现选择点**：是否有多种合理方案，导致不同的功能结果、数据变化、权限、成本或交付范围？
2. **判断重要性与归属**：选错会有什么具体后果或返工？属于用户取舍，还是应由 Agent 采取的普通工程防护？
3. **核对已有答案**：需求、当前资料或有效项目规则是否已经解决？文件原文只是依据，适用性由你解释。
4. **判断当前时机**：当前步骤必须确定才 ASK_NOW；可继续独立步骤则 DEFER；可查事实不清先 INSPECT；已明确或普通实现细节可 PROCEED。

程序核对字段、枚举、引用原文/JSON pointer、文件版本、会话和当前卡片。风险严重性、是否发生、是否需要取舍及自然语言对应均是 LLM 判断。没有额外审核模型或固定提问配额。

## 最小候选

```json
{"candidate_id":"saving","decision_key":"receipt.saving.policy","field":"小票保存方式","category":"business_rule","question":"识别后何时入账？","impact":"影响错误识别是否直接进入账本。","suggested_action":"ASK_NOW","options":[{"id":"A","option_key":"review.before.save","label":"核对后入账","tradeoff":"可修改金额等字段，点击确认后保存。"},{"id":"B","option_key":"save.automatically","label":"自动入账","tradeoff":"步骤少，但识别错误会直接进入账本。"}]}
```

候选还可带 evidence_refs、depends_on、priority、allow_defer、memory_intent、scope_key、conditions、material_change、engineering_risks 与 history_matches。引用使用 context 或真实读取器返回的 source_id，pointer 与 quote 可同时核对；interpretation 是 LLM 解释，不是用户授权。未读资料放请求 resources；不要编造来源。

category 为 business_rule / access_control / data_privacy / cost_external / scope / engineering。suggested_action 为 ASK_NOW / INSPECT / DEFER / PROCEED。priority 为0–100，数字越小越先展示，由你决定。

## 可选风险与覆盖说明

风险说明用于解释取舍，不自动触发问题。engineering_risks 写在对应候选中；recoverability 只能为 easy / costly / irreversible / unknown，恢复办法写入 condition/consequence 等说明字段，不能用整句替代枚举。severity 为 low / medium / high，product_choice 为 yes / no / uncertain。

选项可附 risk_level、risk_warning、risk_basis=observed/potential、risk_reason、risk_condition 与 risk_evidence_refs。资料引用只证明文字存在，风险含义与是否现实由你判断。risk_* 文案不参与业务身份比较。敏感操作继续遵守宿主权限。

coverage 是同次提取的简短依据，维度为 data_storage / access_visibility / automation_confirmation / external_cost / failure_recovery / scope_delivery，最多六项，不必填满。每项 dimension/status/reason，status 为 resolved/candidate/not_applicable/uncertain，可附 evidence_refs/candidate_ids。覆盖记录不证明没有遗漏。

history_matches 可带真实 memory_id/revision、same/related/conflict/different_scope 和 rationale。相似不等于同一选择；只有范围、标识和规则状态核对可用、且你明确请求沿用时才复用。
