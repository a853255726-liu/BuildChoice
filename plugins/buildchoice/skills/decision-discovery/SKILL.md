---
name: decision-discovery
description: 在 BuildChoice 决策卡开启的开发任务中识别重要产品取舍，结合项目资料和已有选择提出建议，保存可追溯的用户决定。普通咨询、已有明确答案和低影响实现细节不发卡。
---

# 关键实现选择与项目上下文

提示版本：`candidate-extractor-v3.8`。你负责重要性、业务含义、资料适用性、语义等价与提问时机；程序核对格式、真实引用、身份、版本与记录状态。工具和文档不授予操作权限。

## 取得一次上下文

在实际开发且决策卡已开启时，使用本轮真实 Hook 句柄调用 `buildchoice_context(session_handle, query, paths)`。路径仅选 README、当前修改涉及的配置等直接资料；返回待答/已答/暂缓项、项目记忆、有效来源和 snapshot_id。优先复用其中的 source_id 与已返回原文，不先另开审计会话，也不重复查询 status 和 memory。已有充分上下文时直接使用，无须固定重复调用。

先处理当前待答卡。已有有效卡用原任务与版本继续；过期卡用新激活键重新展示，不能把等待或过期当成同意。已有已答记录且需求范围未变时沿用，不再询问。暂缓项在你判断相关依赖即将到达时重新评估；无关工作正常继续。新的任务范围使用实际本轮原文，不拼接或伪造用户消息。

`omitted` 和 `content_truncated` 表示本次返回被截断；必要时缩小查询或增加预算。部分读取只能引用已返回范围。追加资料时再调用 context；缺少读取记录才使用审计读取器。带 `since=先前snapshot_id` 可取得文件哈希、决定版本和状态的字面差异。文件变了只提示证据复核，业务影响与是否重新确认由你判断。

## 提出业务建议

按 [候选规则](references/candidate-rules.md) 判断选择点、实质后果、用户归属、已有答案与当前时机。结合功能正常、错误、重复和部分失败的结果分析取舍。按需从 [场景探针](references/scenario-probes.md) 选择最多两类视角；没有相关选择就正常继续，不凑问题。不同权限、成本与数据行为不能强行合并。

在同一次推理中给每个候选 `suggested_action=ASK_NOW/INSPECT/DEFER/PROCEED`，按你给出的 priority 排序；普通工程防护自行处理。重要性、风险词、原文引用及相似检索结果都不能由程序自动证明业务结论。需要示例时读 [开发正反例](references/examples.jsonl)。

调用 `buildchoice_screen_candidates(request)`。最小候选包含 candidate_id、稳定 field/category、question、impact、2–3个 options 和 suggested_action；选项包含 id/label/tradeoff。引用放在候选的 evidence_refs，不放请求顶层；复杂工程风险也是候选字段。Schema 随工具提供。request 提供原始 task_text、phase、next_step、候选数组、真实 session_handle 和新 idempotency_key。零候选可直接给出整体 suggested_action 与简短 coverage。

检查 `validation_status`，它只描述引用与记录是否可用。程序核验失败时先修正事实或参数，不把它误认为业务上必须问用户。`suggested_action` 是你的业务建议；只有可用的 ASK_NOW 项才激活，并原样展示当前卡片，一次一张。暂停该选择所影响的步骤，其余工作可继续。

同一选择沿用 decision_key 与 option_key，范围用 scope_key/conditions，实际行为用 value/behavior/conditions。纯解释或风险文案改写不表示业务改变。实质业务变化如未体现在结构化字段中，明确填 material_change=true；需要新一轮选择时调用 prepare_revision。引用变化本身不撤销原选择。

普通记忆只供参考。只有你判断同一行为与范围、明确 memory_intent=reuse 且稳定身份/版本/当前长期规则核验可用时才沿用。发现冲突或适用范围不清时由你决定补查、询问或暂缓，不能把高相似分数当授权。

## 理解用户回复并记录

字母、序号和完整选项名称可能已由 Hook 直接登记；先看本轮结果，不重复写入。自然回复含义明确、但 Hook 仍显示待答时，使用 `buildchoice_reply_interpret`，传当前 task_id、decision_id、revision、choice_id、本轮真实原文中的精确 quote、解释 reason 和 session_handle。例如“采用核对后保存，金额日期都可修改，请继续并记录”，确实对应原卡时可在同一轮登记，无需让用户重复回复字母。

语义对应由你负责：否定、疑问、多选、引用他人话、尚未决定或新增实质业务条件时不能记成选择，按实际意图讨论、澄清或修订。服务端只核对消息来源、原文、当前卡片和版本；记录为 llm_interpreted_user_reply，不是程序独立证明理解正确。仅在返回记录成功后说明已保存，不模拟 Hook、不直接改 SQLite。

普通确认自动形成项目参考，不主动追问长期保存。“保存这个决定”不自动升级为长期规则；用户明确要求长期记住或管理记忆时再使用 [decision-memory](../decision-memory/SKILL.md)，或直接使用 context 中现成的 management_request/记忆结果。范围明确的修改按该 Skill 处理。

## 文档、代码关联与测试

需要人可读记录或交接时调用 `buildchoice_decision_document`。默认只返回文档；write=true 保存专用生成文件，不覆盖手写文档。先检查用户选择、未决项、范围和引用复核提示，不把生成文档当成新授权。

代码关联是可选功能，仅在需要追溯时登记真实文件位置与哈希。测试、验收和结果解释使用 Codex 原生能力，不要求准备 BuildChoice 验收集合或独立认证。兼容实验工具仅在用户明确要求时使用；current_pass=true 只对应该实验声明范围。
