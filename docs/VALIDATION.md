# BuildChoice · 开发与测试

本次轻量调整只运行相关检查：读取观察 6 项、决策/关联 28 项、Skill 3 项、实验兼容 2 项，以及实际 MCP 和 Hook 打包/源代码与运行时初始化；未重跑完整回归。回调测试为隔离合成事件，不表示已替换当前安装或覆盖全部工具读法。支持范围见[读取观察](PROJECT_READS.md)。

候选增强本机检查：新增 20 项风险/语义回归，覆盖历史检索与隔离、源哈希/指针/原文/解释、工程取舍和普通细节、零候选诊断、可选风险展示、文案身份稳定与行为/范围变更。完整执行 132 项，131 项通过、1 项因符号链接权限跳过；真实 STDIO MCP 检查风险卡与自然选项确认通过。来源和确认测试使用合成 Hook，不代表独立的 LLM 风险发现效果实验。风险发现边界见[说明](CANDIDATE_RISKS.md)。

本指南面向贡献者，说明如何复现实现和协议检查。日常安装与使用见[README](../README.md)，安装异常见[故障排查](TROUBLESHOOTING.md)。

## 基础检查

在 Python 3.11+ 环境中，从仓库根目录执行：

~~~bash
python -m pip install -r requirements.txt
python -m unittest discover -s checks -v
python checks/smoke_mcp.py
python checks/check_package.py
python scripts/build_distribution.py
~~~

| 检查 | 覆盖范围 |
|---|---|
| 单元回归 | 候选分流、会话与确认、版本、来源变化、缓存恢复、路径边界、记忆生命周期、验收判定和失效 |
| STDIO MCP | 实际服务初始化、工具调用、设置通知、模拟 Hook、跨聊天记忆、显式测试采集及关闭模式 |
| 源码与运行包 | 初始化、文件与依赖、Schema、文档链接、校验和、插件入口、doctor 与行为采集 |
| 分发包 | 核心运行包和插件包，输出至 dist，并附 SHA256 文件 |

启用原生设置与决策卡时提供 16 个 MCP 工具；只关闭决策卡时为 8 个，完全关闭时为 4 个。工具列表与调用时都会执行开关校验。

检查使用独立临时目录，记录保留以便排查。可通过 BUILDCHOICE_CHECK_ROOT 指定目录。Windows 的符号链接检查需要相应系统权限；缺少权限时会报告跳过，不能据此声称所有路径用例均已通过。

## 浏览器行为检查

安装开发依赖和 Playwright Chromium：

~~~bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
~~~

将 BUILDCHOICE_TEST_BROWSER 设置为浏览器可执行文件路径，或者使用 Playwright 默认安装的 Chromium，然后执行：

~~~bash
python checks/run_receipt_demo.py --out receipt-results.json
~~~

同一套用例检查识别字段展示、修改后保存、确认前不入账及取消不入账。正确版本应通过；提前入账和忽略修改两个错误版本应失败。详见[记账示例](../examples/receipt_review/README.md)。

## 自动化与结果解释

[GitHub Actions](https://github.com/a853255726-liu/BuildChoice/actions) 在 PR、main 推送或手动触发时运行检查，包括 Windows 路径边界和 Linux 集成/浏览器作业。查看对应提交的作业结果、跳过项及产物；不同提交或不同环境的结果不能直接替代本次检查。

测试入口与夹具保存在 checks 和 examples/receipt_review。安装及会话操作步骤见[端到端测试](END_TO_END_TESTING.md)。

## 自然语言记忆管理验证

专项新增 20 项；本机完整回归 152 项中 151 项通过、1 项因符号链接权限跳过。实际 STDIO MCP、源代码/运行时包初始化与 Skill 打包发现通过。

`checks/test_memory_management.py` 使用隔离账本和合成 Hook 事件验证明确长期保存、名称歧义后澄清、已选项定位、当前聊天指代、项目隔离、句柄所有权/过期、动作/版本替换、修订、冲突、生命周期与幂等审计。普通确认、Agent 传入编号、文件中的指令、引用及含糊消息均不能升级。合成事件验证实现边界，不表示完成真实用户授权。

`checks/smoke_mcp.py` 通过真实 STDIO MCP 和 Hook CLI 覆盖自然保存及拒绝无授权调用；`checks/check_package.py` 验证插件发现路径及新 Skill 被打包。新进程需更新插件与运行时，不能把旧进程的行为视为新版本结果。
