# 候选提取规则

只扫描当前任务及直接开发依赖。五类内部覆盖：功能/业务规则，身份/权限/共享，数据生命周期/隐私，费用/外部影响，重要范围/高返工选择。每类不要求产出候选。

四道门槛：

1. 实质影响：A 与 B 会改变产品行为、隐私、成本、验收或重要返工。
2. 用户归属：业务意图、产品偏好或许可，不能只因为存在两种技术方案就询问。
3. 未明确：尚无可信适用的决定。已明确且无冲突时不再发问，有资料未读则先查。
4. 当前相关：当前任务或直接依赖；不为假想的未来功能打断用户。

反事实自检：Agent 选 A 而用户要 B，会造成什么具体差异？不能说明则通常排除。

排除一般框架、函数命名、代码组织、可逆低影响样式、已有答案、无关远期功能和抽象“安全是否重要”。相近候选合并，但不同权限/成本/数据处理决定不能为凑少量字段强行合并。

## 请求形状

工程风险不能全塞进敏感 risk_flags。保留原敏感标记及加强确认规则；工程方案通过 engineering_risks 分开记录 direction、severity、consequence、condition、recoverability、product_choice，可附 relevance。高/中后果且 product_choice=yes 的相关取舍不能被 engineering_detail=true 静默跳过；不影响当前步骤用 DEFER，影响不清用 INSPECT；product_choice=no 的普通工程实践不强制发卡。

direction 可用 data_integrity / backup_recovery / performance / scalability / availability / vendor_lock_in / compatibility_migration / deployment_rollback / resource_cost / security_permissions / maintainability。它们是发现视角，不是提问配额，也不是独立风险评估结果。

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
