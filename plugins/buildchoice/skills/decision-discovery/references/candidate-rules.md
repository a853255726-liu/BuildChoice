# 候选与程序校验的边界

按四个步骤判断，不把模糊程度或风险标签直接当作追问理由：

1. **发现选择点**：是否有多种合理方案，导致不同的功能结果、数据变化、权限、成本或交付范围？
2. **判断重要性与归属**：选错会有什么具体后果或返工？属于用户取舍，还是应由 Agent 采取的普通工程防护？
3. **核对已有答案**：需求、当前资料或有效项目规则是否已经解决？文件原文只是依据，适用性由你解释。
4. **判断当前时机**：当前步骤必须确定才 ASK_NOW；可继续独立步骤则 DEFER；可查事实不清先 INSPECT；已明确或普通实现细节可 PROCEED。

程序核对字段、枚举、引用原文/JSON pointer、文件版本、会话和当前卡片。风险严重性、是否发生、是否需要取舍及自然语言对应均是 LLM 判断。没有额外审核模型或固定提问配额。

## 从语义判断到提交

例如用户要识别后保存小票，但没有约定错误识别是否直接入账：先判断“核对后保存”和“自动保存”是否会产生重要不同后果、是否已有答案，以及当前是否必须确定。若用户已明确“核对后保存”，就不再提问；若当前只做识别，可暂缓保存取舍。

这只是语义例。24 个[正反例](examples.jsonl)使用 semantic-choice-example.v1，保留任务、可考虑的取舍、后果和时机；不是 MCP 输入，也不证明当前项目已评估风险。实际请求按[结构化内容](decision-content.md)和当前工具 Schema 生成。

## 风险与可选覆盖说明

风险说明用于解释取舍，不自动触发问题。engineering_risks 写在对应候选中；recoverability 只能为 easy / costly / irreversible / unknown，恢复办法写入 condition/consequence 等说明字段，不能用整句替代枚举。severity 为 low / medium / high，product_choice 为 yes / no / uncertain。

选项必须声明 risk_assessment；识别到具体风险时才附 risk_level、risk_warning、risk_basis=observed/potential、risk_reason、risk_condition 与 risk_evidence_refs，依据和触发条件遵守结构化内容规则。资料引用只证明文字存在，风险含义与是否现实由你判断。风险文案与评估状态不参与业务身份比较。敏感操作继续遵守宿主权限。

coverage 是同次提取的简短依据，维度为 data_storage / access_visibility / automation_confirmation / external_cost / failure_recovery / scope_delivery，最多六项，不必填满。每项 dimension/status/reason，status 为 resolved/candidate/not_applicable/uncertain，可附 evidence_refs/candidate_ids。覆盖记录不证明没有遗漏。

history_matches 可带真实 memory_id/revision、same/related/conflict/different_scope 和 rationale。相似不等于同一选择；只有范围、标识和规则状态核对可用、且你明确请求沿用时才复用。
