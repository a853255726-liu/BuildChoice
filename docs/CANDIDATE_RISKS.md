# V3 候选校验、历史语义与工程风险

当前 Codex 判断重要性、产品后果、资料适用性、方案等价和询问时机，通过 suggested_action 提交 ASK_NOW / INSPECT / DEFER / PROCEED。Python 检查格式、引用、身份、版本与记录状态，返回独立的 validation_status。

## 历史：检索与复用分开

提取前优先使用 buildchoice_context 一次取得当前任务、相关记忆与指定资料，也可使用 buildchoice_memory 查询。加权词语/中文短语/双字词机制包含字段、问题、全部选项、范围与条件，不调用额外模型。当前 Codex 判断 same / related / conflict / different_scope，可附 history_matches：

```json
{"memory_id":"M123456789ABC","revision":1,"relation":"related","rationale":"同样涉及保存，但属于不同数据与使用范围"}
```

编号须换成实际检索结果。history_review 分开报告语义声明、来源当前性、稳定键与范围匹配，语义声明不授权复用。普通 reference 不自动取代当前确认；长期规则复用需要 LLM 声明 memory_intent=reuse 并建议 PROCEED，程序再核对当前状态、decision_key、option_key/value、category、scope_key/conditions 和结构化一致性。LLM 显式建议 ASK_NOW 时，不由程序改为静默复用。

## 证据：原文、解释与结构化约束分开

evidence_refs 可同时提供 source_id、quote、pointer、interpretation；服务端读取实际文件并核对哈希，检查每一项定位，不会因为有 pointer 就忽略错误 quote。interpretation 始终是 Agent 的语义解释，不证明用户确认。

relation=constraint、pointer=/chosen 且决定身份和范围一致的限定 JSON，可用于比较结构化字面值；程序报告 applicable_constraint / observed_values 等信息，是否适用仍由 LLM 判断。普通文字标为 constraint 也只是解释，程序不推导其业务含义。不同事实字段不会机械判成互相冲突；规则与同一结构化 chosen 不一致时提示复核，不替用户选择方案。引用失效或定位错误时需补查，原用户选择保留。

## 工程取舍与敏感标记分开

engineering_risks 支持 11 个视角：数据完整性、备份恢复、性能、扩展性、可用性、供应商锁定、兼容迁移、部署回滚、资源成本、安全权限、长期维护。每项声明 severity、consequence、condition、recoverability、product_choice，可附 relevance。没有复杂数值评分，声明的后果与严重性仍由 Codex 判断。

这些字段用于解释取舍，不是程序的风险评分或分流规则。priority=0..100 只按调用方声明排序，同优先级保持输入顺序；allow_defer 由 LLM 声明，缺省允许。risk_flags 不授予或撤销宿主操作许可。

“SQLite 还是 PostgreSQL”不是面向用户的好问题。应结合实际目标，解释“单人简单使用”与“多人同时编辑且保留修改”在数据、成本和后续迁移上的差异。

## 客观诊断与零候选

MCP 只检查声明字段、真实引用、来源当前性与身份。程序不按风险词、severity、engineering_detail 或 next_step 推导业务分流，也不主动生成“可能遗漏风险”诊断。引用错误、未读资源、无效覆盖依据或记忆身份不匹配时要求补查。

零候选可以继续。coverage 与 risk_review 保持 LLM 声明属性，不构成完整性证明。重要选择是否遗漏仍由 Codex 结合实际任务检查，不增加全仓库扫描或独立审核轮次。

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

实际行为/值/适用范围应记录在 option_key、value、behavior、conditions、category、scope_key；这些变化会重新检查确认。自然语言的实质变化无法可靠静态判断时，Codex 必须如实设置 material_change=true。同一内容换本次 candidate_id 不重复修订。稳定 option_key 的同义改写仍兼容，稳定键不是行为正确性的证明。

来源、风险引用和决策记录状态纳入缓存失效。缓存快照不匹配时，需读取当前状态后使用新幂等键；已有确认不被改写。当前任务自身的合法修订不被误判为外部来源突变，相关来源文件仍由快照监测。

语义等价、工程影响、发生条件是否现实、提示文字是否准确依赖当前 Codex 推理。服务端核对身份、状态、原文、哈希、结构化字面值与范围。文件变化只标注引用待复核，不撤销用户选择。上下文与恢复见[流程说明](CONTEXT_WORKFLOW.md)。
