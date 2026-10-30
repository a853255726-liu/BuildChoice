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

每个候选提供 candidate_id、field、category、question、impact、why_user_choice、needs_user_choice、current_dependency、risk_flags、evidence_refs、options、recommended_option_id、recommendation_reason。

category：business_rule / access_control / data_privacy / cost_external / scope / engineering。

needs_user_choice、current_dependency、可选 relevance：yes / no / uncertain。不确定不能写成确定事实。engineering_detail 可选，但不能覆盖风险标识。

risk_flags：privacy、personal_data、external_transfer、payment、irreversible_delete、publish、security、access_control、cost。

options 为 2–3 个对象，id 为 A/B/C，含 label 与 tradeoff，可附结构化 value；互斥含义由主 Agent 负责表达。推荐 ID 可为空；非空时必须来自现有选项。

evidence_refs 仅用真实 source_id，并提供 pointer 或 quote。来源关系可标 fact / constraint；该标记不能把文档升级为用户授权。未读资源使用 path 与 covers 字段，不编造读取记录。

## 新手语言

“允许第三方处理简历”说明信息会发到外部服务；“使用付费 API”说明可能产生实际费用。不要只问 OAuth、JWT、RBAC、ORM 等未解释术语。普通工程技术选择由 Agent 处理。

## 卡片处理

服务端四状态不等同原 NLI 三行动。仅 ASK_NOW 可激活卡；每次一张。解释、不确定、混合指令和自由表述不能自动落为确认。高后果操作仍需要宿主原生许可。
