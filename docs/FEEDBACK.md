# 开发后反馈

反馈帮助普通用户判断产品怎样运行、哪里偏离原意或有未明确约定的重要行为，并能直接提出调整。

## 用户看到什么

1. 使用变化：用实际操作和结果建立认识。
2. 值得优先看的地方：重要差异、未明确约定的行为及影响。没有发现就简短说明。
3. 具体检查缺口：只有影响使用或当前判断时才出现，说清操作/画面、影响、下一步与处理者。没有重要缺口时整节省略；不为每个代码检查重复谨慎声明。
4. 修改意见入口：用户直接说哪个操作应该怎样变化，Agent 负责定位并说明处理方式。

相关资料检查、真实测试和操作检查分别显示，详细 evidence/limits/scope 按需查看。缩短反馈不能提高证据强度，缺口重要性和内容含义由模型判断；程序不证明语义正确或风险完整。

## 开发前与开发后分开

规划未来体验时保留原有场景生成、展示、真实认可和开发前冻结流程。对已完成改动反馈时先定位并接续原任务，enable(purpose=feedback)。有原基线就 compare/create；没有则 inspect 当前文件、检查相关操作后 supplement。当前文件记录不能当成开发前状态，补充检查不能断言本次新增或原有。

项目资料参照、用户要求及已确认决定保留不同来源。没有找到要求时，不能直接认定产品偏离要求；反馈过程也不生成假的事前认可。

## 内容与校验

新 MCP create/supplement 请求带 report(version=behavior-feedback.v1, overview=所提交发现的编号)，每条 finding 提交 display(title, check, 可选 impact/gap)。check 为 observed/tested/read/not_checked，由当前依据及具体行为覆盖限制可用等级。gap 为 situation/effect/next_step/owner，约束为80/80/100字符和 agent/user。

程序拒绝空白、多段格式、超长、未知概述引用、无依据的检查等级、重要完全未检查项被隐去、空泛缺口及假历史。报告文件不能升级成实际测试返回。校验失败要求修正，不自动截断。旧记录可读取，新展示不改写旧数据。

自然语言反馈仍绑定真实当前消息。fix 保留要求并修正，change_requirement 需要可信决定与新要求版本，investigate/defer 保留待办。记录意见不等于修改已经完成；后续报告关联 previous_review_id。代码、要求、资料或检查记录变化时复核，历史保持。

## 内容、流程与呈现的维护边界

反馈内容以 Skill 的 feedback-content.md 为准，定位已完成工作及原基线／当前检查接续归 product-review.md，原生卡和展示返回 message 归 conversation.md，结构与固定输出归 feedback_report.py。跨角色的共同判断与短版由 guidance.py 统一维护，Markdown 标记块通过 sync_guidance.py 更新。

current/supplement 表示当前检查，不包含正式前后行为对照；这不等于所有旧资料均不存在。原要求、旧文件、正式比较和运行证据分别表达。supplement 仍不接受补造场景或任填 change_origin；变化来源保持 uncertain。

文件 quote 不匹配时返回 EVIDENCE_REPAIR_REQUIRED，issues 含字段、路径、start_line/end_line 和规则；仅帮助定位修复，不输出敏感全文，也不证明 finding 的业务判断正确。内容格式仍使用 FEEDBACK_CONTENT_REPAIR_REQUIRED，其他归属／状态错误按原异常处理。
