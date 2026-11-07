# 指令与回复记账


用户已经明确指定行为、修改范围或再次确认当前决定时，调用 `buildchoice_record_instruction(request)`，不先 screen/prepare_revision/activate，不为已确定的行为编造其他选项。先从 context 取得已有 decision_id 和当前 revision；更新使用 expected_revision=当前版本，同一选择保留 decision_key。传本轮完整实际 user_message（不含 Hook 附加上下文）、精确 quote、解释 reason、session_handle 和 idempotency_key。decision 提供 decision_key、field、scope_key/conditions 和一个 choice，choice 至少有 label/value；不同账本等范围的行为在 value 中完整表达，仅修改指定范围，保留其余行为。新决定用 expected_revision=0，无 decision_id。

已有提案但尚未发卡时，可用 decision_id、expected_revision 和 choice_id 直接记录真实指令选择。再次确认已有选择时省略 decision/choice_id，保留现有版本；若 Hook 已记录，直接沿用。程序只核对原话哈希、精确引用、归属、版本和重试，不判断否定、假设、引用、建议或问题是否构成决定；这些由你判读，含糊时先澄清。记录来源为 llm_interpreted_user_instruction，不能说成程序独立证明理解正确。

成功返回 recorded=true 后再说明已保存；document.status=synchronized 表示生成文档已同步，pending 表示账本已保存但文件待补写，重试原请求或用 decision_document(write=true) 恢复。不要手工写 Markdown 来代替工具记账，不直接改 SQLite，不把重复确认当新版本，不把旧回执当当前决定。新聊天先读 context 的项目记忆和 document 状态，再结合必要的生成文档恢复；不要只凭文档猜测账本状态。

字母、序号和完整选项名称可能已由 Hook 直接登记；先看本轮结果，不重复写入。自然回复含义明确、但 Hook 仍显示待答时，使用 `buildchoice_reply_interpret`，传当前 task_id、decision_id、revision、choice_id、本轮真实原文中的精确 quote、解释 reason 和 session_handle。例如“采用核对后保存，金额日期都可修改，请继续并记录”，确实对应原卡时可在同一轮登记，无需让用户重复回复字母。

语义对应由你负责：否定、疑问、多选、引用他人话、尚未决定或新增实质业务条件时不能记成选择，按实际意图讨论、澄清或修订。服务端只核对消息来源、原文、当前卡片和版本；记录为 llm_interpreted_user_reply，不是程序独立证明理解正确。仅在返回记录成功后说明已保存，不模拟 Hook、不直接改 SQLite。

普通确认自动形成项目参考，不主动追问长期保存。“保存这个决定”不自动升级为长期规则；用户明确要求长期记住或管理记忆时再使用 [decision-memory](../../decision-memory/SKILL.md)，或直接使用 context 中现成的 management_request/记忆结果。修改实现选择使用指令记账入口，记忆管理不能代替决定修订。

异步原生回复必须有对应的新 Hook 句柄。NO_OBSERVED_REPLY、USER_MESSAGE_CONTEXT_MISMATCH 和 HOOK_CONTEXT_UNAVAILABLE 都保持 recorded=false；遵循工具的 recovery，不用同一句柄换接口重试。新旧消息的换行会规范化，但不会把不同消息当成同一条。不要让用户为插件诊断反复点选；需要保存时用一次普通消息恢复可信关联。

