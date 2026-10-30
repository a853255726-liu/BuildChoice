# BuildChoice 插件

BuildChoice 在 Codex 中帮助用户确认重要实现选择，提供按需决策卡、本地选择记录和项目文件证据审计。默认使用 Prompt-first，V3 独立开启，无小判别模型或推理服务。

## 安装

从插件目录执行，使用实际运行时路径：

```bash
python setup.py --workspace /path/to/your-project --runtime-root /path/to/BuildChoice --install
```

安装器准备核心依赖；已有环境可指定 `--reuse-python /path/to/venv/bin/python`，Windows 使用实际 Scripts/python.exe。已有绑定指向另一工作区时，指定独立 `--data-home`。

可由根目录 `scripts/build_distribution.py` 构建运行包，再通过 `--bundle /path/to/buildchoice-core-0.7.0.zip` 初始化。该版本不再接受模型依赖、设备或 worker 端口参数。

插件仅注册 UserPromptSubmit Hook，用于澄清原则与实际回复关联。Hook 信任由宿主正常审阅，初始化器不修改审批。项目账本保存于 `.buildchoice_audit`。
