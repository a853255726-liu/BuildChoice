# BuildChoice · 端到端测试

本指南面向贡献者和部署验证人员。按安装、对话、实现和项目切换检查完整使用流程。

## 工程集成

先执行[开发与测试](VALIDATION.md)中的单元、STDIO、打包和浏览器检查。CI 使用模拟用户事件，可以验证协议与受控行为；插件在真实 Codex 会话中的加载和回复关联需要另行检查。

## 真实 Codex 会话

使用已登录、支持插件的 Codex 和独立测试项目，按[安装说明](../README.md#安装)安装并开启决策卡。

1. 运行 python scripts/buildchoice_doctor.py --host --json，检查绑定、插件启用与 Hook 信任。保留未知或失败项；仅看到插件启用不代表真实回调已执行。
2. 在新会话提出“帮我做一个记账小程序，支持识别购物小票的金额和类别”，不预先指定保存方案。
3. 记录是否发现自动保存与核对后保存的选择，选项说明是否清楚，是否先读取已有约束。没有生成相关卡片、重复提问或无关阻塞也应记录。
4. 按实际卡面单独回复选项。查询决策状态，检查当前选项、版本及 user_message_observed 来源。该消息必须来自真实会话，不使用脚本构造的回调替代。
5. 完成实现后，请 Codex 检查该选择是否落实。在已有命令权限下显式运行行为测试，核对逐项结果、current_pass 和声明的输入范围。测试遗漏或断言不足应记录为缺口。
6. 修改相关代码后再次查询，旧结果应失效。修复、重跑并重新验证后，应形成新记录。
7. 分别测试已经明确保存策略、只改样式和纯咨询的请求，检查是否出现多余的阻塞提问。
8. 另开同项目聊天检索已确认选择，检查普通参考与长期规则的区别；执行遗忘和恢复，确认召回状态改变且历史保留。

记录 Codex 版本/模型、BuildChoice 提交 SHA、输入需求、卡片文本、Hook 关联证据、行为用例、退出码及异常。公开材料应移除凭据、个人路径和会话敏感内容。

## 相关设计参考

- [GitHub Spec Kit clarify](https://github.com/github/spec-kit/blob/main/templates/commands/clarify.md)：按维度检查未明确的选择。
- [GSD quick discussion](https://github.com/gsd-build/get-shit-done/blob/main/get-shit-done/workflows/quick.md)：围绕用户可见行为讨论取舍。
- [OpenSpec workflows](https://github.com/Fission-AI/OpenSpec/blob/main/docs/workflows.md)：关联需求与验证证据。
