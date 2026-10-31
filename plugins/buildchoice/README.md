# BuildChoice 插件

BuildChoice 在 Codex 中帮助用户确认重要实现选择，提供按需决策卡、本地选择记录和项目文件证据审计。默认使用 Prompt-first，V3 独立开启，无小判别模型或推理服务。

## 安装

从插件目录执行，使用实际运行时路径：

```bash
python setup.py --workspace /path/to/your-project --runtime-root /path/to/BuildChoice --install
```

安装器准备核心依赖；已有环境可指定 `--reuse-python /path/to/venv/bin/python`，Windows 使用实际 Scripts/python.exe。已有绑定指向另一工作区时，指定独立 `--data-home`。

可由根目录 `scripts/build_distribution.py` 构建运行包，再通过 `--bundle /path/to/buildchoice-core-0.8.1.zip` 初始化。该版本不再接受模型依赖、设备或推理 worker 端口参数。

插件仅注册 UserPromptSubmit Hook，用于澄清原则与实际回复关联。Hook 信任由宿主正常审阅，初始化器不修改审批。项目账本保存于 `.buildchoice_audit`。

0.8 提供按需验收准备和验证工具。条件由 Agent 从当前已确认选择推导；验证 MCP 不执行项目命令。行为测试通过原有授权路径显式调用运行时的 `scripts/buildchoice_run_verification.py`，再提交返回的 execution_id。运行时目录与 Python 可从安装数据目录的 binding.json 读取，默认 `~/.buildchoice`；独立安装使用相应 BUILDCHOICE_DATA。没有真实测试不能通过，输入变化后旧通过结果失效。
