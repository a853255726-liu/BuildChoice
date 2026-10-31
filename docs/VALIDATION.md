# BuildChoice · 开发与测试

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

启用原生设置与决策卡时提供 15 个 MCP 工具；只关闭决策卡时为 8 个，完全关闭时为 4 个。工具列表与调用时都会执行开关校验。

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

单元和协议测试使用模拟 Hook，浏览器测试使用合成识别数据。它们验证实现契约和受控行为，不证明真实 Codex 会话已加载插件、实际候选发现质量或真实相机/OCR 链路有效。真实宿主检查与产品评测方法见[端到端测试](END_TO_END_TESTING.md)。
