# Clarification Gate

Prompt-first 的 Agent 澄清策略与按需决策证据审计工具。

普通任务使用简洁的澄清原则：能查项目文件就先查，需要业务取舍再询问，信息足够则直接推进。重要任务可以建立决策账本，将关键选择关联到真实文件，并记录复核过程。

## 功能

- **决策账本**：登记决定、取值、影响、理由和来源。
- **文件证据**：实际读取工作区文件，保存原文快照、相对路径、时间和 SHA256。
- **结构化核对**：使用 JSON pointer 定位值，检查取值与类型、多来源字面冲突。
- **引用定位**：检查精确引文是否存在；语义含义与业务适用性供复核者判断。
- **来源变化检测**：文件变化后重新提示复核，保留旧快照与处理历史。
- **复核与导出**：记录接受、修改或询问的意见，导出 Markdown / JSON。
- **多入口**：本地浏览器工作台、CLI、MCP 工具和 Codex 插件。

系统检查显式登记的关键决定，不自动枚举全部实现选择。文件由审计工具本次读取，不等同于原 Agent 先前已读取或业务已经授权。

## 快速启动

需要 Python 3.11+。本地工作台仅使用标准库，无需安装模型、GPU、API Key 或第三方依赖。

```bash
git clone https://github.com/a853255726-liu/change-note.git clarification-gate
cd clarification-gate
python scripts/gate_audit.py serve
```

Windows 可以双击 `START.cmd`。启动器会打开带有本地会话令牌的浏览器链接。保持命令窗口开启，按 Ctrl+C 停止。

如需审计另一个目录：

```bash
python scripts/gate_audit.py --workspace /path/to/project serve
```

打开工作台后：

1. 新建任务审计。
2. 读取工作区内的证据文件。
3. 登记关键决定，并选择 JSON 字段路径或精确原文作为依据。
4. 查看定位结果，记录处理意见，导出报告。

示例来源是 `examples/migration.json`，包含 `auth` 和 `keep_legacy_api`。可以通过 `/auth` 核对鉴权方式。

## CLI

```bash
python scripts/gate_audit.py start "接口迁移" --task "检查鉴权与兼容策略"
python scripts/gate_audit.py read <audit-id> examples/migration.json
python scripts/gate_audit.py list
python scripts/gate_audit.py report <audit-id> --out audit-report.md
python scripts/gate_audit.py review <audit-id> <decision-id> --disposition ask --note "请负责人确认映射规则"
```

登记决定时，`--value` 接受 JSON 值，`--refs` 接受引用数组。字段结构见 [MCP 与数据接口](docs/API.md)。

## MCP 接入

MCP 和插件入口需要固定的核心依赖：

```bash
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements.txt
# macOS/Linux: .venv/bin/python -m pip install -r requirements.txt
```

在 MCP 客户端中配置实际 Python 和项目绝对路径：

```json
{
  "mcpServers": {
    "clarification_gate": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/clarification-gate/scripts/codex_gate_mcp.py", "--native-settings"],
      "cwd": "/path/to/clarification-gate",
      "env": {
        "CLARIFICATION_GATE_WORKSPACE": "/path/to/your-project",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Windows 的 command 使用虚拟环境内 `Scripts/python.exe` 的实际路径。默认提供四个按需审计工具：

| 工具 | 用途 |
|---|---|
| `gate_audit_start` | 建立任务审计 |
| `gate_audit_read` | 实际读取文件并取得来源 ID |
| `gate_audit_decision` | 登记决定与引用 |
| `gate_audit_report` | 返回结构化报告和 Markdown |

## Codex 插件

从源码安装已准备的核心环境：

```bash
python plugins/clarification-gate-controls/setup.py --workspace /path/to/your-project --runtime-root /path/to/clarification-gate --reuse-python /path/to/venv/bin/python --install
```

已有绑定指向其他工作区时，使用独立的 `--data-home`。插件内含原生设置与生命周期 Hook；Hook 通过宿主的正常审阅流程启用。

插件运行模式：

| 模式 | 行为 |
|---|---|
| Prompt 优先（默认） | 注入澄清原则，不暴露分类器推断工具，可按需审计 |
| 自动选择 | 在已配置分类器资源时由 Agent 决定是否调用 |
| 强制调用 | 在受支持的本地流程检查当前轮次的分类器调用回执 |
| 完全关闭 | 关闭插件中的审计和分类器工具，保留设置入口 |

仓库保留可选分类器的后端和字段推断代码。模型权重及匹配的产物清单需单独部署；默认路径不依赖这些资源。详见 [模型接入](docs/MODEL_BACKEND.md)。

## 数据存储

审计账本位于目标工作区 `.gate_audit/ledger.sqlite3`，保存任务、来源快照、决定、复核和事件，不自动上传。单个 UTF-8 文件上限为 256 KiB；仅从目标工作区读取，私有配置目录、符号链接和工作区外路径被排除。

本地服务只绑定 `127.0.0.1`，API 使用随机会话令牌与 Host/Origin 检查，适合本机单用户使用。

## 项目结构

```text
clarification_gate/
  desktop/           # 账本、Web、策略、契约、MCP 客户端与本地服务
  backends/          # 可选分类器接口与 NLI 后端
  predictor/         # 字段级推断和证据路由
scripts/             # CLI、MCP 入口、服务管理与分发构建
plugins/             # Codex 插件、安装器和 Hook 启动器
configs/             # 可移植默认配置
docs/                # 架构与接口
examples/            # 最小使用示例
```

构建核心运行包和插件包：

```bash
python scripts/build_distribution.py
```

输出位于 `dist/`。运行状态、模型文件、个人配置和生成的导出文件应保留在本地。
