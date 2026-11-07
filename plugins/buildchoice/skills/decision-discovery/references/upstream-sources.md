# 上游来源与本地适配（0.15.2）

维护本 Skill 时查看；执行普通任务不需要加载本文件或许可证全文。参考文件是本地改写的精简指导，未安装、执行或依赖完整上游插件，不引入新的模型服务或网络依赖。后续更新按任务行为验证，不能用上游版本变化直接覆盖本地约束。

| 本地内容 | 上游文件与固定版本 | 许可证 |
| --- | --- | --- |
| interface-content.md | [Anthropic frontend-design](https://github.com/anthropics/skills/blob/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/skills/frontend-design/SKILL.md) | [Apache-2.0](../licenses/Apache-2.0.txt) |
| documentation-consistency.md | [OpenAI Agents SDK docs-sync](https://github.com/openai/openai-agents-python/blob/3e0e89374f629c974929054e56e823a43c91a013/.agents/skills/docs-sync/SKILL.md) | [MIT, Copyright (c) 2025 OpenAI](../licenses/OpenAI-MIT.txt) |
| evidence-debugging.md | [Superpowers systematic-debugging](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/systematic-debugging/SKILL.md) | [MIT, Copyright (c) 2025 Jesse Vincent](../licenses/Superpowers-MIT.txt) |
| feedback-content.md 的验证证据原则 | [Superpowers verification-before-completion](https://github.com/obra/superpowers/blob/3be5aad3dd2400ef23b15680969f4bcd3b6d7b8b/skills/verification-before-completion/SKILL.md) | [MIT, Copyright (c) 2025 Jesse Vincent](../licenses/Superpowers-MIT.txt) |

适配于 2026-11-07：按实际任务选择相关专题，保持用户意图和真实约束；合并到现有实施与检查，不追加固定阶段、确认轮次、审阅角色或全量审计。保留有效证据复用，删除上游专用技术栈、路径、语言、命令和强制关联 Skill 的要求；移除原版固定失败次数阈值和逐消息重跑验证的规定。具体变化也写在各本地文件末尾。

上游的署名与许可随改写材料保留；BuildChoice 对这些本地适配负责，不表示上游作者认可本项目或证明适配效果。安全专项和完整上游工作流未在本次接入。

## 本地指导维护

共同规则、角色短版和三个专题审阅短版由源码 buildchoice/desktop/guidance.py 维护，scripts/sync_guidance.py 只同步明确标记块；--check 核对漂移。流程、卡片协议、反馈内容及具体方法仍归各原文件。生成检查不证明双语含义一致或模型判断有效；独立审阅只按任务加载选中短版，不安装完整上游流程。
