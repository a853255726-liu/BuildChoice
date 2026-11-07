# 产品预期、行为审阅与集中决策

四个正式入口均在日常工具集中。按工具公布的 action 专用 Schema 提交 request；内部身份由你查询并传递，用户只需自然表达。关闭模式不能记录新数据。

产品体验审阅且宿主具备独立上下文时，按[独立上下文审阅](independent-review.md)以 review_policy=independent 启用；不把完整聊天传给审阅者，不增加模型服务。普通低影响任务保持原流程。

## 已完成工作：先定位对象

1. 用 context 的任务、改动范围、执行结果和相关资料定位用户指的真实项目、改动与交付版本。能查清不问；只有确实存在两个不同对象时才澄清。不要把最近讨论的另一个项目自动视为目标。核对实际根目录、task_id、文件版本和快照；哈希关联不能代替语义定位。
2. 接续原任务，experience(enable, purpose=feedback)。有原冻结预期和代码起点时 compare → behavior_review(create)，继续使用原版本。
3. 没有正式旧比较时 workspace_snapshot(inspect, scopes=实际当前范围)，检查相关操作后 behavior_review(supplement, current_snapshot_id=该记录)。inspect 只保存此刻，不是开发起点，不重新 save/present/freeze 一份预期让用户认可。原要求、旧文件、正式比较与运行观察分别说明；supplement 的变化来源仍保持 uncertain。
4. 需要独立审阅时按[独立协议](independent-review.md)准备当前材料与适用专题，保存真实输出；然后按[反馈内容](feedback-content.md)组织重要发现和证据。没有新产品取舍不额外发卡。

## 启用与开发前准备

以下准备流程用于开发前规划；已完成工作使用前一节的反馈分支，不补做事前认可。

1. 用户要在开发前规划/整理/确认产品体验或开启完整流程时，`buildchoice_experience(enable)` 使用本轮真实 task_text。已存在任务用 task_id 接续；不因句柄存在就默认启用。先查 context.product_tasks 或 experience(status)，复用当前版本和未解决问题，避免重建任务。
2. 重要的明确选择用原有 record_instruction 保存；重要未决选择按下节集中处理。技术细节自行处理。
3. `experience(save)` 提交场景数组：触发 → 操作 → 具体行为。每项重要 behavior 保持稳定 behavior_id 和独立来源 user/decision/project/ai/unresolved。用户来源提交真实完整原话及精确引用；项目来源引用实际已读资料；决定来源绑定当前可信版本。不能把整句话里的 AI 补充冒充已确认决定。修订时未改动的行为可用 source.kind=recorded 加原 scenario 身份/版本和 behavior_id 复用原来源；程序要求行为身份与文字完全相同，不能借旧来源确认新内容。含义冲突由你识别、说明并修正或提问；程序不验证语义。
4. `experience(present)` 冻结要展示的具体版本。将返回 message **完整展示给用户**，包含各项来源、范围和条件。工具生成不证明 UI 交付，未展示内容不得纳入认可。用户在后续真实消息中明确认可、修改、讨论或暂缓时，`acknowledge` 提交此次 presentation_id、具体场景版本和 accepted/pending/discuss/deferred。只记录明确认可；含糊回复继续澄清。保存、展示、用户沉默均不等于认可，也不提升长期规则。
5. 开发前 `experience(freeze)` 保存当前采用的场景版本及混合审阅状态。未认可的重要行为先处理；用户明确允许按已说明方案继续时记录认可。不为不重要事项制造确认。
6. **首次修改前**用 `buildchoice_workspace_snapshot(capture)` 将 expectation_id 与明确任务 scopes 绑定，建议选择相关源码目录以覆盖新增/删除文件；excluded_paths 排除项目特定的私人文件。Git 暂存、未暂存和未跟踪文件及无 Git 项目使用相同快照。检查每项 status，未采集项不能当完整起点。

任务范围外文件首次修改前 `snapshot(extend)`，timing=before_first_edit 仅在你实际尚未修改时使用；已修改则 timing=already_modified，记录起点缺失，不补造历史。不在开发完成后重新生成一份预期代替原冻结基准。需求改变应生成新决定、新场景版本及新的开发基线；保留前轮记录。

## 集中决策

先用 screen 创建候选。启用任务后 `buildchoice_batch_decisions(present)` 传最多 3 个独立、当前有效的 ASK_NOW 身份/版本；按 [对话呈现](conversation.md) 将 presentation.native_request 交给宿主原生问题卡。仅无原生组件时才展示固定 message。依赖问题先后分批，已明确要求不重问。单卡与批次不可同时等待同一回复。

后续真实用户消息如“第一选 B，第二按推荐，第三再讨论”，由你解释并用 submit 提交仅已明确的条目，含 selected/deferred/discuss；未回答项省略。current_recommendation 只可用于冻结批次明确有推荐的项目。“都按推荐”不能替无推荐项作选择。含糊、否定、疑问、竞争选项、新条件不得解释成选择；新含义走原有修订/指令或继续讨论。

提交对整个冻结集合核验后原子保存所提交的选择。任一过期/错误归属/来源错误则全部拒绝；重新查询并解释原因，不把失败说成部分已完成。已明确选择不重答；其他条目继续保留。暂缓或切换批次可 suspend，保留待办，之后用当前未答版本重新 present。新聊天必须重新展示，旧聊天批次不能直接收新确认。单卡调用保持兼容。

## 开发后审阅

1. `snapshot(compare)` 使用实际开发前 baseline_id，对相同范围重新采集并生成真实内容差异。检查 scopes、uninspected、diff_truncated；范围外、缺少起点或已清理的内容不作确定变化结论。不能仅凭快照认定变化由 Codex 单独造成。
2. 由你结合冻结场景、真实差异、代码、Codex 原生测试和运行观察，提交 `buildchoice_behavior_review(create)`。每条 finding 关联冻结 scenario 和实际检查的 behavior_ids；程序为遗漏行为补“无法判断”。先说用户会遇到什么变化，再给技术依据。
3. judgment 与 evidence 各自填写。仅模型分析用 llm；文件引用用 file 并提供真实路径、行范围和精确 quote。测试用 test、运行观察用 runtime，记录实际覆盖的 tested_behaviors、结果与 limits。任务启用后的受支持 PostToolUse 会给 observation_id；引用实际返回的精确内容，不能从 exit_code=0 推断测试确实运行或覆盖了所有行为。Hook 不判断命令是不是测试，含义与覆盖由你核对。只有文件日志而没有真实工具记录时，系统标记执行未核验；宿主不支持记录时照实使用该等级，不补造句柄。
4. 额外行为必须区分 observed_change/preexisting/uncertain。本次变化须有真实差异中的文件依据；原有行为应查起点内容，无法确定就 uncertain。没找到要求来源不能等同“AI 擅自错误新增”。
5. 按 [反馈内容](feedback-content.md) 提交结构化 report 和每项 display，使用 create/supplement/status 返回的 message 展示使用变化、重要差异、仅在重要时出现的具体检查缺口和自然语言反馈入口。finding.expected_behavior 来自原冻结行为，补充检查的 reference 只是实际参照，不自动成为用户认可。详细 evidence/limits/scope 按需查看；保持真实检查程度，但不把例行局限反复塞到正文。未检查内容不能被其他通过测试的路径覆盖。

## 反馈、恢复与文档

用户自然语言反馈后用 review(feedback)，绑定完整当前真实 user_message、精确 quote 和具体 finding：

- fix：保留预期，记录待修正；用 Codex 实施修复后重新 compare/create，previous_review_id 指向前轮审阅。新审阅中仍用原基线，不静默改要求。
- change_requirement：先用可信 record_instruction 记录决定或修订；保存关联该决定的新场景版本，再反馈 decision/scenario。跨聊天不能修订旧聊天决定时，在当前聊天记录明确的新任务范围决定并关联；旧决定不会因此被静默撤销或升级长期规则，若涉及旧项目规则按原有记忆修订流程处理。
- accept_extra：只接受当前具体额外行为和明确范围，保存 note；不表示测试通过，也不授予文件、网络、支付、部署权限。
- investigate：继续调查，保持未解决。
- defer：保存暂缓，保持原决定，之后可恢复。

场景/决定/代码/依据变化后旧审阅需复核；历史保留。experience(status) 返回原预期、审阅、反馈及批次；跨聊天复用记录，但新认可须使用本聊天重新展示和真实消息。document 状态 pending 时调用 experience(document) 重试发布，不能重新创建场景版本来修文档。生成文件保护用户手写内容。任务完成/用户关闭时 experience(close)，后续可 enable 原 task_id 恢复。

快照保存在本地安装数据目录 product-snapshots 下，不提交源码仓库、不上传。文件 256 KiB、单快照 8 MiB、项目 64 MiB、保留 30 天，清理发生于后续采集；prune 提前清理只删除正文，保留哈希与历史。重要证据过期后明确说明无法复查。
