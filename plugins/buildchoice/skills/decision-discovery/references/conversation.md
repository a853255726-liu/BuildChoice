# 聊天内原生选择卡与非技术反馈

## 决策卡：先使用宿主原生组件

新候选先按 [结构化内容](decision-content.md) 生成并通过校验。card_activate 或 batch_decisions(present) 返回 presentation；它由已冻结的问题、选项、推荐和风险信息派生。原始 card 和版本不因展示清理而改动。

当前宿主提供 request_user_input_async 时，将 **presentation.native_request 原样作为参数** 调用：

```javascript
request_user_input_async(presentation.native_request)
```

参数只有 questions，每项只有 title 和 options，适配聊天内可点选的问题卡。原生组件由宿主绘制，BuildChoice 不另建网页。不要先粘贴文字卡再问一遍；不要删改选项的产品后果和风险，不额外手写第二个“推荐”，不显示后台 ID、版本哈希或调用流程。推荐项预选不等于提交或认可。

title 只保留问题；宿主自动编号，选项不再重复 A/B。默认不加“产品影响、推荐理由、可讨论、等待选择”等说明。impact、推荐依据和风险评估状态保存在 presentation.details，用户需要时再解释；风险后果与触发条件仍在选项内显示。未填写旧风险信息按未评估处理，不显示“已确认无风险”。

若只有 request_user_input，按该工具当前公布的 Schema 和可用模式转换，同样完整保留问题/后果/选项含义；不能强行在不支持的模式调用。都没有时才使用固定 Markdown message，并简短说明当前只能用文字选择，不假装已有可点选 UI。

presentation.bindings 只供你绑定答案：question_index 对应本批问题，answers.text 对应展示给用户的完整选项，choice_id 指向原冻结选项。用户提交后，等待真实 Hook 的新句柄，再核对决定/版本并记账。单卡若 Hook 未直接识别原生表单包装，使用 reply_interpret 绑定本轮原话；批次使用 submit 的完整 user_message。不要把表单返回、默认预选、旧聊天回复或你自己的展示内容当成用户确认。

用户的自定义回答可以是讨论、暂缓或新增条件；有明确变更时修订，不用近似标签或只取字母来忽略新条件。无需展示内部映射给用户。

### 异步回复与 Hook 的接续

收到点选回复不代表宿主一定产生了新的 UserPromptSubmit。先使用本轮新句柄读取 context.reply_binding；仅当 can_interpret_reply=true 才调用 reply_interpret。Hook 已自动登记的直接复用。可信 Hook 收到单题原生包装时，只对题目和完整选项精确匹配；自定义回复、额外条件及批次不由单卡解析器自动确认。

缺少新句柄，或者 reply_binding 表示 awaiting_new_hook_message 时，不尝试旧句柄、不拼接包装重试、不切换到 record_instruction，也不重新展示同一张问题卡。工具返回 recorded=false/unbound 时按 recovery 接续；它不代表已经保存。确实需要落账时，仅解释一次“已收到你的选择，但尚未取得可登记的消息关联”，再请用户发一句普通消息。已有对话指令是否允许继续工作仍由宿主规则判断；插件登记失败不自动撤销用户原话，也不额外授予权限。

## 完成反馈的呈现

正式 create/supplement/status 返回的 message 是主要非技术反馈，直接展示，不用命令、文件列表或测试数量代替。[反馈内容](feedback-content.md)维护顺序、重要程度、具体缺口和自然语言反馈入口，不在本文件另建一套标准。

已有工作反馈的对象定位与原比较／当前检查分支见[产品流程](product-review.md#已完成工作先定位对象)。不补造旧基线或要求重新认可。宿主的原生决策卡不证明应用已有图形界面；交付表面按实际实现说明。

用户要求试用命令时再给运行目录、目的与预期结果，保留完整可用示例；内部记录编号不作为普通用户必须理解的概念。
