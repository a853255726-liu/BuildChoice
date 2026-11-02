# V3 候选校验、历史语义与工程风险

本次实现基于 GitHub BuildChoice 的 0.10.1 提交 445bb407aef195c496435f54ab3dbfc2e4b70d73，保持 Codex + Skill + MCP + SQLite、现有稳定键和 Hook 回复解析。没有修改 Handle、任务生命周期、宿主审批或数据库表结构。

## 历史：检索与复用分开

提取前使用现有 buildchoice_memory 按相关行为与后果检索。加权词语/中文短语/双字词机制包含字段、问题、全部选项、范围与条件；不增加 Embedding 或新 LLM。当前 Codex 在一次提取中判断 same / related / conflict / different_scope，可附 history_matches：

```json
{"memory_id":"M123456789ABC","revision":1,"relation":"related","rationale":"同样涉及保存，但属于不同数据与使用范围"}
```

编号只是示例，须换成实际检索结果。history_review 分开报告 Agent 的语义声明、来源当前性、稳定键与范围匹配；can_authorize_reuse=false 始终保留，这个声明本身不能授权。普通 reference 不自动取代当前确认；长期规则继续要求当前版本、状态、decision_key、option_key/value、category、scope_key/conditions、风险与 memory_intent=reuse 一致。关系冲突、适用性变化或 material_change=true 均不能静默复用。新字段缺省保持旧记录语义。

## 证据：原文、解释与结构化约束分开

evidence_refs 可同时提供 source_id、quote、pointer、interpretation；服务端读取实际文件并核对哈希，检查每一项定位，不会因为有 pointer 就忽略错误 quote。interpretation 始终是 Agent 的语义解释，不证明用户确认。

只有 relation=constraint、当前决定身份/范围匹配、pointer=/chosen 且原值与选项字面值一致的限定 JSON 约束，可以支持 PROCEED。legacy 的 field/chosen 仍兼容；有 decision_key 时按稳定键匹配，可附 scope_key、conditions。普通文字标为 constraint 仍是 interpretation_pending，不能绕过确认。不同事实字段的值不会被机械判成互相冲突；同一决定的不同结构化 chosen 则需补查。失效、含糊、冲突或未读资料先返回 INSPECT，不让旧确认或工程细节标记覆盖它。

## 工程取舍与敏感标记分开

engineering_risks 支持 11 个视角：数据完整性、备份恢复、性能、扩展性、可用性、供应商锁定、兼容迁移、部署回滚、资源成本、安全权限、长期维护。每项声明 severity、consequence、condition、recoverability、product_choice，可附 relevance。没有复杂数值评分，声明的后果与严重性仍由 Codex 判断。

- 原敏感 risk_flags 保持加强确认，不将全部新工程风险归入其中。
- 当前必须决定、后果显著且 product_choice=yes 的取舍可 ASK_NOW，不受 engineering_detail=true 静默跳过。
- 当前不依赖的取舍 DEFER；中高后果的产品影响仍不清楚时 INSPECT。
- 普通、低风险、可逆或已明确的工程实践可 PROCEED，不因理论风险制作卡片。

“SQLite 还是 PostgreSQL”不是面向用户的好问题。应结合实际目标，解释“单人简单使用”与“多人同时编辑且保留修改”在数据、成本和后续迁移上的差异。

## 有界诊断与零候选

MCP 只检查 next_step 和通过哈希/引用核验的片段。当前字面信号包括删除表/字段、覆盖已声明数据文件、浏览器存储、外部请求、明确部署及不兼容迁移。匹配只证明相关文字出现，不证明代码已执行、数据会丢失、调用一定外传敏感信息或方案必然不可接受；常见否定表达会被排除，仍不是通用语义分析。

候选未覆盖相关信号时返回 POSSIBLE_MISSING_PRODUCT_RISK、requires_inspection=true 和 screen_status=INSPECT，指导原 Codex 补查/补充候选。即使 candidates=[] 也如此，不生成虚构卡。普通工程处理可通过相应 engineering_risks.product_choice=no 解释；该覆盖仍标 agent_declared，不是独立充分性证明。零候选、无信号时可以继续，但 risk_review 始终标 coverage_complete=false，明确不证明没有遗漏。不扫描全仓库，不设额外审核轮次。

## 选项风险展示

原标题、选项、利弊、推荐和回复方式保持。仅高风险且有足够依据的选项追加风险提示；普通选项文本不变。

```json
{
  "id":"A", "option_key":"storage.browser",
  "label":"仅在当前浏览器保存", "tradeoff":"实现简单，不需要服务器",
  "value":"browser_only", "behavior":"浏览器保存唯一副本",
  "risk_level":"high", "risk_basis":"potential",
  "risk_warning":"清除浏览器数据或更换设备后，记录可能无法恢复。",
  "risk_condition":"仅有浏览器副本，且用户清除站点数据或更换设备",
  "risk_reason":"当前方案没有独立备份，另一设备无法取得原记录。"
}
```

potential 必须有明确发生条件和推导依据，显示“风险提示（可能发生）”；它是 Agent 基于方案的条件推导，不是测试结论。observed 必须有可核验 risk_evidence_refs，显示“风险提示（项目资料中的风险）”；核验引用存在不等于独立证明资料语义或风险事实。无依据的高风险文字被抑制并要求补查。高风险仍可选择，也不强制推荐另一个选项。

示意效果：

```text
A. 仅在当前浏览器保存：实现简单，不需要服务器
   风险提示（可能发生）：清除浏览器数据或更换设备后，记录可能无法恢复。
B. 云端保存并支持备份：方便跨设备使用，但需账号和持续服务费用
```

## 身份、版本与兼容性

risk_level / risk_warning / risk_basis / risk_reason / risk_condition / risk_evidence_refs 是展示依据，不进入选项语义比较。去重、同任务重筛、项目记忆与输入快照分别处理它们，风险文案调整不自动生成新决策版本或废除确认。修改文案应重筛并用新幂等键，不主动要求 prepare_revision；显式 prepare_revision 仍代表新一轮确认。

实际行为/值/适用范围应记录在 value、behavior、conditions、scope_key；这些变化会重新检查确认。自然语言的实质变化无法可靠静态判断时，Codex 必须如实设置 material_change=true，不得藏在展示字段中。稳定 option_key 的同义改写仍兼容，稳定键不是行为正确性的证明。

来源、风险引用和历史状态仍纳入缓存失效。筛选缓存内部版本更新为 2，旧缓存需读取当前状态后使用新幂等键；不迁移或改写旧确认。当前任务自身的合法修订不被误判为外部来源突变，但新旧来源文件仍被快照监测。

边界：语义等价、工程影响、发生条件是否现实、提示文字是否准确仍依赖当前 Codex 推理。服务端验证的是可客观检查的身份、状态、原文、哈希、结构化字面值、范围与字面信号；没有独立语义审核、完整风险发现保证或新的操作授权。
