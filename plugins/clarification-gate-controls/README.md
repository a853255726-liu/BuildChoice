# Clarification Gate 插件

提供 Prompt-first 原则、原生模式设置、按需决策证据审计与可选分类器接入。

## 从源码安装

先在运行时项目建立 Python 3.11+ 环境并安装根目录 `requirements.txt`，然后：

```bash
python setup.py --workspace /path/to/your-project --runtime-root /path/to/clarification-gate --reuse-python /path/to/venv/bin/python --install
```

Windows 使用实际的 `Scripts/python.exe` 路径。已有绑定指向另一工作区时，使用独立 `--data-home`。

也可以由根目录 `scripts/build_distribution.py` 构建核心运行包，再用 `--bundle` 初始化：

```bash
python setup.py --workspace /path/to/your-project --bundle /path/to/clarification-gate-core-0.3.0.zip --install
```

初始化器默认仅准备核心依赖。`--with-classifier` 只安装可选依赖，模型资源和匹配的清单需要另外部署。

新安装默认 Prompt-first，可通过四个 MCP 工具建立账本、读取来源、登记决定和取得报告。审计数据保存于绑定工作区 `.gate_audit`。

UserPromptSubmit Hook 注入原则，其他 Hook 支持可选强制调用。非托管 Hook 通过宿主正常审阅流程启用，初始化器不修改信任状态。
