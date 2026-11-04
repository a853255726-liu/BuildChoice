# 候选提取规则

只扫描当前任务及直接开发依赖。首先围绕「功能要如何运行、失败时会怎样、数据会怎样变化」寻找关键实现选择，不把所有技术方案或风险标签都变成用户问题。五类内部覆盖仍用于补漏：功能/业务规则，身份/权限/共享，数据生命周期/隐私，费用/外部影响，重要范围/高返工选择；每类不要求产出候选。

按下面的顺序判断，而不是将模糊程度直接当作追问理由：

1. **发现选择点**：当前功能是否存在多种合理处理方式，会导致不同的行为、数据结果、异常处理、恢复能力、性能、成本或兼容性？没有不同结果的内部实现细节不提取。
2. **判断重要性与归属**：Agent 选 A 而用户实际需要 B，会有什么具体、显著的功能后果或返工？此取舍是否属于用户的功能预期、使用规则、成本/风险偏好或授权，而不是 Agent 应按工程常规自主解决的事项？
3. **核对已有答案**：用户要求、项目文件、有效历史规则或明确工程约束是否已解决？不因存在不同实现方式而重问。材料可读但未读时先 INSPECT，普通文字解释不能自行充当用户确认。
4. **判断当前时机**：仅保留当前任务或直接依赖的未解选择；不影响当前步骤时可 DEFER，确需现在确定时才考虑 ASK_NOW。最终状态由 MCP 结合证据和依赖分流。

风险是分析功能后果的辅助维度，不是独立发卡门槛。对于风险，尽量串起「触发条件 → 可能的失败/代价 → 对功能或用户的实际影响 → 可恢复性/缓解措施 → 是否形成需要用户取舍的不同方案」。区分：需要用户决定的功能取舍、应由 Agent 自主采取的工程防护，以及仍须遵守宿主权限的敏感操作。没有足够依据时标为潜在风险，不能宣称后果已经发生。

排除一般框架、函数命名、代码组织、可逆低影响样式、已有答案、无关远期功能和抽象“安全是否重要”。相近候选合并，但不同权限/成本/数据处理决定不能为凑少量字段强行合并。

## 请求形状

工程风险不能全塞进敏感 risk_flags。保留原敏感标记及加强确认、宿主授权规则；功能失败、数据正确性、异常恢复、性能、兼容等工程后果通过 engineering_risks 记录 direction、severity、consequence、condition、recoverability、product_choice，可附 relevance。严重不等于用户必须选择：只有存在实质性的功能结果取舍且 product_choice=yes，才作为用户决策候选；product_choice=no 的普通工程修复、防护和最佳实践由 Agent 自主完成。高/中后果且 product_choice=yes 的相关取舍不能被 engineering_detail=true 静默跳过；不影响当前步骤用 DEFER，影响不清用 INSPECT；外传、付费、删除、发布仍走现有敏感标记与宿主权限控制，不因 product_choice=no 而绕过。

direction 可用 data_integrity / backup_recovery / performance / scalability / availability / vendor_lock_in / compatibility_migration / deployment_rollback / resource_cost / security_permissions / maintainability。根据当前功能还要主动考虑错误结果、重复执行、部分成功、异常回滚与恢复等情形；这些情形映射到已有方向和 consequence/condition，不新增工具字段。方向是发现视角，不是提问配额，也不是独立风险评估结果。

可附 history_matches（真实 memory_id、revision、same/related/conflict/different_scope 和 rationale）；语义判断由当前 Codex 推理产生。MCP 不把相似或 Agent 声称 same 视为允许复用。scope_key 与 conditions 表达实际适用范围，普通历史参考不升级为长期规则。

Option 可附 risk_level=low/medium/high、risk_warning、risk_basis=observed/potential、risk_reason、risk_condition、risk_evidence_refs。高风险提示须有来源或明确条件推导；旧选项无需补字段。风险展示字段不进入选项语义身份，实际行为/适用性变化使用 value、behavior、conditions 或 candidate.material_change=true。结构化字段变化由服务端检查，无法判定的自然语言实质变化由 Codex 如实标记。

EvidenceRef 的 interpretation 是语义解释，绝非确认；可同时提交 pointer、quote 供核验。指针原值、原文与文件哈希任何一项不匹配先检查。只有限定的结构化约束可支持直接继续，普通文字的 interpretation 不单独满足此条件。

每个候选提供 candidate_id、field、category、question、impact、why_user_choice、needs_user_choice、current_dependency、risk_flags、evidence_refs、options、recommended_option_id、recommendation_reason。

category：business_rule / access_control / data_privacy / cost_external / scope / engineering。

needs_user_choice、current_dependency、可选 relevance：yes / no / uncertain。不确定不能写成确定事实。engineering_detail 可选，但不能覆盖风险标识。

risk_flags：privacy、personal_data、external_transfer、payment、irreversible_delete、publish、security、access_control、cost。

options 为 2–3 个对象，id 为 A/B/C，含 label 与 tradeoff，可附结构化 value；互斥含义由主 Agent 负责表达。推荐 ID 可为空；非空时必须来自现有选项。

evidence_refs 仅用真实 source_id，并提供 pointer 或 quote。来源关系可标 fact / constraint；该标记不能把文档升级为用户授权。未读资源使用 path 与 covers 字段，不编造读取记录。

## 新手语言

“允许第三方处理简历”说明信息会发到外部服务；“使用付费 API”说明可能产生实际费用。不要只问 OAuth、JWT、RBAC、ORM 等未解释术语。普通工程技术选择由 Agent 处理。

## 卡片处理

服务端使用确定性四状态。仅 ASK_NOW 可激活卡；每次一张。解释、不确定、混合指令和自由表述不能自动落为确认。高后果操作仍需要宿主原生许可。

## 覆盖记录

coverage 在同次提取中附带，不另做一轮检查。最多六项：data_storage / access_visibility / automation_confirmation / external_cost / failure_recovery / scope_delivery。每项 dimension、status、reason 必填，evidence_refs 与 candidate_ids 可选；status 为 resolved / candidate / not_applicable / uncertain。

只填本次相关维度。资料未查清用 uncertain，reason 不超过 300 字符；来源必须真实采集。候选为空也可记录已明确或不适用的依据；这些声明不能证明没有遗漏，不单独决定发卡。
