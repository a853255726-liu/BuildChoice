# BuildChoice · 决策卡使用说明

决策卡帮助你确定会影响产品行为的选择，例如数据如何保存、谁能访问、是否自动执行。普通技术细节由 Codex 处理。安装后默认使用 Prompt-first，开启决策卡后，可在原对话中逐项选择方案。

## 开启与关闭

在仓库或已绑定的运行时目录执行：

~~~bash
python scripts/buildchoice_decisions.py pilot
python scripts/buildchoice_decisions.py settings
python scripts/buildchoice_decisions.py off
~~~

pilot 开启决策卡，settings 查看设置，off 关闭决策卡及项目决策记忆。Codex 原生设置中也可选择“决策引导：试用 / 关闭”。要完全关闭 BuildChoice，执行：

~~~bash
python scripts/buildchoice_settings.py off
~~~

恢复 Prompt-first 使用 python scripts/buildchoice_settings.py prompt。修改设置后，支持工具列表通知的 Codex 会刷新可用工具；更新插件代码后需重新连接 MCP 或重启 Codex。

## 在对话中使用

直接提出开发需求，例如“给现有项目加登录”。BuildChoice 结合当前需求、对话和项目资料检查是否存在需要你决定的选择。资料已有明确答案时先沿用；需要选择时，一次显示一张卡，说明选项、影响和建议。纯咨询、解释和已明确的普通修改照常进行。

你可以回复卡面上的 A / B，也可以先要求解释。要记录明确选择，请单独发送选项，或使用“卡号 + 选 A”。自由回答、引用他人的回复、同时包含其他指令的消息不会自动记为确认。

需要改变选择时，直接告诉 Codex。它会提出新版本，再等待你确认；旧选择和相关代码位置保留，便于检查需要调整的实现。

## 暂停、切换和恢复

你可以先讨论方案，也可以转去处理其他任务。切换任务不会确认原卡。恢复原任务时，Codex 可重新展示尚未确认的选择。

卡片过期、方案发生修订或另一张卡替代了当前卡后，应根据重新展示的卡片回答。迟到的 A / B 不会确认过期版本。Hook 未启用或未取得信任时，仍可正常交流，但相关选择不能标为已核验。安装问题见[故障排查](TROUBLESHOOTING.md)。

## 查看已做的决定

可以要求 Codex“列出这个任务已确认的选择及相关代码”。实现关联保存真实文件位置与内容哈希；决定修订或文件变化后会提示复核。它帮助定位实现，不代表行为已经测试通过。

需要检查是否落实时，可以说“检查核对后保存的选择是否已经实现”。检查结果取决于已执行的行为测试；没有测试时会保留未验证状态。见[决策落实检查](DECISION_VERIFICATION.md)。

希望后续聊天继续参考已确认选择时，使用[项目决策记忆](DECISION_MEMORY.md)。遗忘会停止主动召回，原历史仍保留。

## 数据和权限

记录保存在当前项目的 .buildchoice_audit/ledger.sqlite3，不由插件自动上传。记录包括选项、版本、消息摘要、相关来源及检查结果，不保存完整聊天全文。

BuildChoice 的选择记录不替代 Codex 对文件、网络、发布或命令执行的权限审批。候选识别依赖当前 Agent 和已读取资料，不能保证发现所有重要选择。

需要对接工具时，参见[MCP 接口](API.md)与[接口契约](DECISION_V3_CONTRACT.md)。
