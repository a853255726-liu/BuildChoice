---
name: decision-discovery
description: 在 BuildChoice 开发任务中用可点选的宿主原生问题卡确认重要产品取舍，并用非技术语言反馈实际行为变化。用户要求规划或核对产品体验时，按任务启用场景预期、冻结基线和行为审阅。咨询和低影响实现细节不发卡。
---

# 关键实现选择

<!-- buildchoice-guidance:entry:start -->
维护版本：`intent-alignment.v1`。

从用户要完成的事理解任务与交付，不以完成清单替代目标。

资料与约束按来源和真实范围使用，现状不自证用户意图。

必要事实先查；重要业务取舍才问，信息足够或有合理可逆默认值就继续。

结论对应真实对象、版本与证据，不补造历史、检查或认可。

按需取证并复用有效结果，不增加固定确认、审阅轮次或全量审计。

记账不授予权限；保留真实消息、归属、版本与幂等边界。

只要求方案时可给有条件建议；按任务读取 decision-discovery 的相关入口。
<!-- buildchoice-guidance:entry:end -->

## 先选当前任务入口

- 普通开发：正常实施与相关检查，不额外建立场景认可或独立审阅。完成反馈按[反馈内容](references/feedback-content.md)说明实际使用变化与重要差异。
- 开发前规划／确认产品体验：先读[产品流程](references/product-review.md)，enable 后整理场景，首次修改前冻结真实采用的预期并采集起点。没有完成的步骤不得称为完成。
- 对已完成或上次改动给反馈：按[产品流程的完成后分支](references/product-review.md#已完成工作先定位对象)接续真实项目、任务与交付，使用原比较或 inspect/supplement；不重新生成预期要求用户认可。
- 明确独立审阅，或产品体验审阅且宿主支持独立上下文：读[独立审阅协议](references/independent-review.md)，启用 independent 策略。首轮只给有来源的事实和实际交付；普通低影响任务直接检查。宿主不支持时说明边界，不把同一上下文自检称独立审阅。

实际开发或实施前按需用 buildchoice_context 一次取得当前有效选择、待答项、相关来源与记忆；已有充分上下文则直接使用。不固定查询 status/memory 或另开审计。检查 omitted/content_truncated，省略不等于已读；新聊天核对项目记忆与 document 同步状态。工具返回 workflow.stage/next_action 时按真实状态接续。

## 选择最短专业参考

按制作、检查或审阅的实际对象选择：[界面内容与交互](references/interface-content.md)、[说明与实现](references/documentation-consistency.md)、[证据驱动排查](references/evidence-debugging.md)。无关任务不加载，不新增固定阶段、确认卡、审阅角色或全量审计。独立材料包的 review_topics 由你按任务选择，不把执行者怀疑点送给首轮。

检查方法按问题选择，功能、结构和实际视觉各按真实依据表达；截图不是前置条件。已有有效结果可复用，工具失败时按[反馈检查方法](references/feedback-content.md#按问题选择检查工具)接续。

## 重要选择怎样处理

- 用户已明确作出重要选择或修订：用 record_instruction，提交完整真实本轮原话、精确引用、原因、当前句柄与幂等键。不要先 screen 或另发卡；更新使用已有身份／版本和稳定 key。重复确认沿用原版本，细节见[指令与回复记账](references/recording.md)。
- 开放式开发或准备改变主要产品行为时：在现有推理中先形成**当前最小拟议方案**（交付范围、主要用户路径及关键数据后果），找出其中未获确认的重要假设；必要时与**一个**实质不同的合理方案对照。只筛影响当前实现的高后果选择，不把普通样式、文案或工程细节变成用户问题。目标都无法从项目与需求推断时先问最少的用途信息；按[候选判断](references/candidate-rules.md)处理，不新增强制规划或确认阶段。
- 仍有重要未决取舍：按[候选判断](references/candidate-rules.md)和[结构化内容](references/decision-content.md)提取，检查 validation_status 后激活 ASK_NOW。优先把返回 presentation.native_request 交宿主原生问题工具；没有原生能力才用固定文字。产品任务可集中最多三个独立问题，普通任务沿用单卡；只暂停受影响步骤。
- 回复已有卡：Hook 已登记就复用，否则按[原生回复接续](references/conversation.md)处理。过期卡、额外条件和含糊回复不能只取字母当选择。
- 原生异步回复缺少新 Hook：先看 reply_binding；can_interpret_reply=false 时不调用回复记账，不复用旧句柄、不重建包装、不切换 record_instruction、不重发同卡。保持未登记，必要时仅解释一次；确需落账再请用户发普通消息。
- 没有重要未决选择：正常继续，不为留记录制造候选；已答不重问，暂缓项到达依赖时再评估。

语义由你判断：疑问、否定、假设、引语不因原话真实就成为决定。只有 recorded=true 才说决定保存，document.status=synchronized 才说文档同步。产品选择是内容澄清，真正的执行权限仍依宿主规则；对用户解释实际后果，不展示内部流程或编号。

## 按需能力

需要发现功能选择点时，按需读[场景探针](references/scenario-probes.md)，最多两类、也可不选；不凑问题。需要例子时读[语义正反例](references/examples.jsonl)，它们不是工具请求。候选内容、风险评估与修复以[结构化内容](references/decision-content.md)及当前工具 Schema 为准。

独立审计、记忆管理、代码关联、提议修订和实验验证仅在确有需求时使用完整工具集。用户明确要求时可通过原生设置切换 tool_profile；切换只暴露入口，不授予操作权限，之后可切回日常。指令记账自动维护生成文档；pending 时按原请求或 decision_document(write=true) 恢复，不直接改 SQLite。

普通确认只形成项目参考，明确要求长期保存或管理时才用[decision-memory](../decision-memory/SKILL.md)。测试优先用 Codex 原生能力；不默认创建验收集合或独立认证，兼容实验接口只在用户明确要求时使用。[上游来源](references/upstream-sources.md)仅维护时查阅。
