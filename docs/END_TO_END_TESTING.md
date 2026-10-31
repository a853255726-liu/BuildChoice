# BuildChoice 0.8：集成与真实宿主验收指南

本指南分清三种不同的证据。**不能把前两种测试当成真实 Codex 用户实验。**

## A. 代码与协议集成（CI 可自动执行）

在仓库根目录安装 `requirements.txt` 和 `requirements-dev.txt`，安装 Playwright Chromium 并设置 `BUILDCHOICE_TEST_BROWSER` 为对应浏览器可执行路径。执行：

```bash
python -m unittest discover -s checks -v
python checks/smoke_mcp.py
python checks/check_package.py
python scripts/build_distribution.py
python checks/run_receipt_demo.py --out receipt-results.json
```

`.github/workflows/integration.yml` 在 PR、main 推送或手动触发时运行以上检查。

**这些检查分别证明什么：**

- 单元：四状态分流、有效回复、不可变决策/验收与证据失效等实现契约。
- STDIO：真正启动 MCP 服务，通过 JSON-RPC 操作真实工具，并由本地子进程模拟宿主 `UserPromptSubmit` 回调。
- 打包：检查源码及运行包的初始化、独立诊断、入口和配置边界。
- 浏览器：针对同一套预先固定的行为断言，运行正确版本、提前保存和忽略修改两种受控错误版本；后两者必须失败。

**这些检查不能证明什么：** 真实 Codex 宿主是否加载插件、Hook 在真实会话中是否受信任、LLM 是否实际发现相关选择、用户是否理解决策卡、验收条件是否独立于 Agent 正确。

## B. 真实 Codex 宿主端到端验收（必须在已登录 Codex 环境执行）

仓库当前没有可供本项目直接调用的已登录 Codex 宿主，因此 CI 不会假装完成此步骤。

在拥有 Codex 插件权限和本地命令执行许可的测试环境中：

1. 在**独立的临时工作区**安装插件，不要覆盖用户日常项目。使用 `python scripts/buildchoice_doctor.py --host --json` 检查插件与 Hook 状态。不要因为只看到插件启用标记就宣布宿主回调已验证。
2. 使用 `python scripts/buildchoice_decisions.py pilot` 开启试用，并用新的 Codex 会话提交：「帮我做一个记账小程序，支持识别购物小票的金额和类别。」不要附加暗示保存方案的后续指令。
3. 检查 Agent 是否按现实项目上下文发现「自动保存 vs 核对后保存」，是否先做来源检查、一次只显示一张相关决策卡。记录漏问、同义重复问和普通工程问题被阻塞情况；**没有生成卡也应真实记录**。
4. 如果出现相关卡，真实用户回复 `B`（以实际卡面为准）。查询 `buildchoice_decision_status`，核对 `user_message_observed`、当前版本及选项。此处只能用**真实宿主提交的回复**，不能使用 Python 构造的 Hook fixture 冒充。
5. 在原生授权下由 Codex 完成相关功能，使用它生成的行为验收条件和真实测试，按需运行采集器与 `buildchoice_verify_decision`。检查逐项结果、`current_pass` 及输入范围。对需求解释错误或用例不充分，必须记录为测试设计缺口。
6. 修改相关实现代码，再读取状态；旧验证应提示 `stale` 或 `current_pass=false`，修复并重新测试后形成新记录。
7. 对照测试：对已经明确保存策略的需求、纯视觉修改、纯咨询分别新建会话，检查没有无意义的阻塞决策卡。

记录至少包含：Codex 版本/模型、基础提示策略、BuildChoice 提交 SHA、Hook 观察证据、真实会话首轮指令、决策卡文本、关联行为测试及退出码、额外轮次/用时、失败情况。公开报告必须去掉个人目录路径、会话敏感信息与凭据。

## C. 产品效果评测（独立于工程验收）

在正式 A/B 运行前，将公开开发命令恢复为原始完整文本，无法恢复的上下文单独标为不可复现；由至少两名不知道实验组别的评审预先标注需要决策和无需追问的任务，冻结 Gold。

- 主指标：`及时发现的 Gold 决策 / Gold 决策总机会`，一条决策每轮最多计一次。
- 质量守护：多余阻塞追问率、提问精确率。
- 成本守护：配对任务的额外时长与工具调用数。
- 0.8 专项：给普通 Codex 与 BuildChoice 同样的**已确认决策和同一组外部行为测试**，比较实现一致率；使用独立写好的正确与错误代码，比较真实偏差检出率和误报率。

配对分析以**原始任务**为独立采样单元，重复运行不得当作新的独立项目。强制保留超时、未回答、无测试和不确定记录，不能只挑插件成功的样例。

## 参考实现及取舍

- [GitHub Spec Kit clarify](https://github.com/github/spec-kit/blob/main/templates/commands/clarify.md)：结构化覆盖分类，但 BuildChoice 只扫描当前直接相关事项，不强制问满数量。
- [GSD quick discussion](https://github.com/gsd-build/get-shit-done/blob/main/get-shit-done/workflows/quick.md)：根据用户看到/调用/运行/阅读的内容提出场景化灰区；BuildChoice 不额外执行独立 planning agent。
- [OpenSpec verify](https://github.com/Fission-AI/OpenSpec/blob/main/docs/workflows.md)：把需求与验证证据联系起来；BuildChoice 目前只对显式声明的本地输入和真正执行过的测试给出有限判断。

原则：保留 Prompt-first 默认设置、V3 独立试用开关、不修改现有用户授权，不把 Agent 的自我解释误当完整性或测试充分性证明。
