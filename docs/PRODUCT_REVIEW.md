# 产品预期与行为差异审阅（0.14.4）

用户只需说“先整理我会用到的产品流程”“按这个体验方案开发”“核对结果是否符合预期”或“解释这次改变了什么行为”。Agent 按当前任务启用，普通开发继续原流程，不要求用户操作数据库或填写内部编号。依赖原有 Hook 与决策引导开启；不是实验开关。无需浏览器自动化或独立测试平台。

## 用户会看到什么

0.14.2 优先使用聊天内可点选的宿主原生问题卡。新内容先经结构化与呈现校验，MCP 返回 presentation.native_request 与后台 bindings，由 Agent 调用当前宿主提供的原生提问工具；后台不会伪造 UI 已展示或用户已选择。标题仅为问题，选项保留后果和风险，额外理由保存在 details 按需解释。无原生组件时保留固定 Markdown 作为明确降级。

开发后审阅返回固定 message，按使用变化、重要差异、必要的具体检查缺口、自然语言意见组织。没有重要缺口时不展示第三节，详细依据和例行限制在 findings.evidence/limits 按需查看。对已完成工作用 enable(purpose=feedback) 接续原任务；无旧基线时 inspect 当前文件再 supplement，不新建预期要求认可。普通任务仍按需启用。workflow.stage/next_action 只描述真实步骤，不替代语义判断。见[反馈说明](FEEDBACK.md)。

- **集中决策**：最多三个适合一起处理的重要问题，说明影响、方案和推荐。可回复“第一选 B，第二按推荐，第三再讨论”。已明确的选择保留，未答、讨论和暂缓项继续保留。依赖问题分批；含糊表达不自动确认。
- **场景预期**：“识别完成后 → 用户点击确认 → 保存消费记录”。每项行为注明用户要求、已确认决定、已读项目资料、AI 推导或尚未明确。保存或展示不代表认可；用户可认可部分已展示版本、修改、讨论或暂缓。认可不改变原始来源，也不创建长期项目规则。
- **开发后审阅**：简述使用变化后，重点呈现可能偏差及重要补充行为；具体检查缺口按重要性呈现，格式或长度的精简不提高结论强度。额外行为区分本次观察到的修改、原有行为和来源不确定。
- **反馈**：“修正实现”保留预期；“修改要求”保存可信决定及新场景版本；“接受额外行为”只接受具体范围，不表示测试通过；“调查”和“暂缓”继续保留未解决状态。

## 工作流与程序边界

日常/完整工具集都提供下列正式工具。Schema 随 MCP tools/list 公布，执行与公布使用同一个严格结构。各请求带真实 session_handle；变更请求带 idempotency_key。同键不同输入拒绝；同一真实消息对同一确认目标的重复解释拒绝冲突。

| 工具 | action | 用途 |
|---|---|---|
| buildchoice_experience | enable, save, present, acknowledge, freeze, status, document, close | 按任务管理稳定场景、来源、认可和冻结预期；恢复/重试文档 |
| buildchoice_workspace_snapshot | capture, extend, compare, status, prune | 保存实际工作区起点，比较真实文本，安全清理正文 |
| buildchoice_behavior_review | create, feedback, status | 关联原冻结预期、实际差异、证据、反馈及历史审阅 |
| buildchoice_batch_decisions | present, submit, suspend, status | 冻结最多三个决定；原子保存明确提交的选择，保留其余项 |

LLM 负责业务含义、来源是否适用于行为、依赖选择、测试语义和行为解释。程序核对真实来源、工作区、身份、版本、文件、精确引用、展示版本、事务和幂等；不使用关键词判定产品语义。场景冲突应由 Agent 解释并修改或澄清，来源真实不证明语义正确。

现有单卡、指令、记忆及上下文入口兼容。单卡与集中批次不能同时占用回复槽。跨聊天可用 experience(status) 读取任务；context 返回 product_tasks 恢复入口。旧聊天展示句柄不能在新聊天收认可，必须用当前 Hook 重新展示。上下文共享不继承确认或宿主操作权限。

## 两个开发前基线

产品预期保存具体 scenario_id/revision、逐项来源、相关决定和认可状态。场景修改追加版本，原预期和历史审阅不覆盖。未改动行为可通过 recorded 来源引用复用原版本的原始来源，程序核对行为身份与文字相同；这不是新的来源类别或再次用户认可。代码基线独立保存任务开始时实际文件内容、相对路径和 SHA256，同时记录工作区身份、Git HEAD/分支/状态（若存在）。比较依据是起点正文，不是 Git HEAD；已暂存、未暂存和未跟踪文件都按实际工作区读取，无 Git 项目也可使用。

capture 在首次修改前使用。extend 添加不重叠范围，before_first_edit 是 Agent 对时间的声明，程序不独立证明此前无人修改。已修改范围用 already_modified 标记缺少起点，不保存伪造历史。compare 重新检查相同范围，生成新增、修改和删除的实际文本差异。单个差异输出超过 64000 字符时标记截断；原快照正文仍受原文件限额管理。

范围外文件未检查；排除、不可读、缺少起点或已清理的内容逐项说明。快照只能证明范围内发生了变化，不能证明全部由 Codex 单独产生。

## 本地快照保护

正文保存到安装数据目录（默认 `~/.buildchoice`，支持 `BUILDCHOICE_DATA`）下 `product-snapshots/<工作区哈希>`，必须在代码工作区外。SQLite 仅保存引用、内容哈希、版本和状态。启动器传递实际自定义安装数据目录。无自动上传、无源码仓库提交步骤。

| 限制 | 默认值/行为 |
|---|---|
| 单文件 | 256 KiB；UTF-8 文本；二进制或其他编码记录排除原因 |
| 单次快照 | 8 MiB；超出限额的文件标记 storage_quota |
| 单工作区正文总量 | 64 MiB；不同任务共用工作区限额 |
| 文件/目录遍历 | 最多 10000 项，超出则要求缩小范围 |
| 保留期限 | 30 天，后续采集时清理；可用 prune 提前清理 |
| 敏感内容 | 排除环境文件、密钥/凭据、私人数据目录、已知敏感名称和检测到的字面凭据；支持额外 excluded_paths |
| 路径 | 拒绝绝对/越界/不受支持路径、符号链接和 Windows junction；存储路径也检查链接 |

敏感内容检测仅为额外保护，不替代项目明确指定的排除范围。不要把私人资料加入任务源码范围。清理只删除受控正文文件，哈希、版本、清理原因和历史审阅保留，旧结论标记不能复查。文件捕获期间观察到变化会标记 concurrent_change_during_capture；多文件快照不声称具有操作系统级原子性。

## 证据与结论

judgment 记录 possibly_matches / possibly_deviates / extra / unknown；证据强度独立保存。

| 证据 | 能支持的结论 |
|---|---|
| llm_analysis_only | 模型根据内容推断，未验证实际行为 |
| actual_code_or_file | 服务端实际读取路径、行范围、引用和哈希；业务解释仍由 LLM 负责 |
| test_execution_result | 真实 PostToolUse 回调中的命令、输出、退出码；测试含义和行为覆盖由 Agent 声明 |
| runtime_tool_observation | 真实工具观察，限记录的交互/输出；不是所有用户路径的证明 |
| report_file_execution_unverified | 实际存在报告文件，但未核验测试或交互执行 |
| missing / changed / unavailable | 缺少证据或需要重新检查 |

PostToolUse 仅在已启用且绑定到该聊天的任务下记录受支持的完成命令结果（Bash / exec_command），拒绝未完成、截断、超限或含检测到凭据的内容。不推断命令是否为测试，不运行命令，不创建语义分类器。无该回调的宿主仍能以代码/文件分析正常完成审阅，证据等级如实降低。记录不证明执行时所有输入不变，原生工具运行与文件快照之间的时间限制必须说明。

每条 finding 指明实际检查的 behavior_ids；遗漏的冻结行为自动列为无法判断。测试通过也只支持声明的测试条件；不覆盖其他关键行为。代码、场景、决定、资料、证据变化或快照内容不可用时，旧报告动态标记 needs_recheck，原内容保留。修复后的报告可关联 previous_review_id；不自动把用户接受额外行为解释为验证通过。

## 数据升级、文档与关闭

旧账本使用增量附加 product_tasks / product_objects / product_operations / product_documents / product_task_hosts / product_active_batches，不改写原 decision.v3 表结构或确认历史。product_objects 保存不可变场景/预期/快照/比较/审阅和追加反馈事件，反馈版本用预期版本校验；SQLite BEGIN IMMEDIATE 防止并发部分成功。

生成的任务 Markdown 以 `BUILDCHOICE_PRODUCT_<任务短标识>.md` 命名，带独立生成标记；手写文件不覆盖，改用 `.generated.md`，两者均占用时保留 pending。写入采用临时文件和原子替换，失败后 experience(document) 从当前账本重新生成，不重建决定/场景。查询时重新检查审阅有效性；要刷新已发布报告用 document。原决策文档保持兼容。

close 停止任务新流程，enable 原任务可恢复；全局 off 或决策引导 off 在入口处拒绝新记录。普通未启用任务不自动采集代码快照、记录产品工具事件或创建场景。

## 指导入口归属

Skill 的 product-review.md 维护规划与已完成工作反馈两条接续路径。feedback-content.md 维护用户应看到的内容；independent-review.md 维护独立材料、宿主与采纳协议。专业审阅可以按任务选 review_topics，省略保持核心审阅；不增加固定阶段、确认或审阅角色。
