# BuildChoice · 名称与升级说明

0.5.0 将程序与接口名称统一为 BuildChoice。Python 和机器标识使用小写 `buildchoice`。这是一次包含接口改名的升级，旧插件与新插件不要同时启用。

## 名称对应

| 项目 | 0.4.x | 0.5.0 |
|---|---|---|
| Python 包 | `clarification_gate` | `buildchoice` |
| 插件目录与安装 ID | `clarification-gate-controls` | `buildchoice` |
| 本地市场 | `clarification-gate-local` | `buildchoice-local` |
| MCP 服务键 | `clarification_gate` | `buildchoice` |
| MCP 工具前缀 | `gate_` | `buildchoice_` |
| 初始化入口 | `plugins/clarification-gate-controls/setup.py` | `plugins/buildchoice/setup.py` |
| MCP 入口 | `scripts/codex_gate_mcp.py` | `scripts/buildchoice_mcp.py` |
| 决策管理 | `scripts/gate_decisions.py` | `scripts/buildchoice_decisions.py` |
| 审计入口 | `scripts/gate_audit.py` | `scripts/buildchoice_audit.py` |
| 分类器管理 | `scripts/manage_desktop_gate.py` | `scripts/manage_buildchoice.py` |
| 调用模式管理 | `scripts/gate_auto_call.py` | `scripts/buildchoice_auto_call.py` |
| 面板管理 | `scripts/manage_gate_panel.py` | `scripts/manage_buildchoice_panel.py` |
| 运行配置 | `configs/codex_desktop_gate.toml` 的 `[gate]` | `configs/buildchoice.toml` 的 `[buildchoice]` |
| 调用模式配置 | `configs/gate_auto_call.json` | `configs/buildchoice_auto_call.json` |
| 安装数据目录 | `~/.clarification-gate` | `~/.buildchoice` |
| 项目账本目录 | `.gate_audit` | `.buildchoice_audit` |
| worker 状态目录 | `runs/desktop_gate` | `runs/buildchoice` |
| 环境变量 | `CLARIFICATION_GATE_DATA` / `_WORKSPACE` / `_V3_SETTINGS` | `BUILDCHOICE_DATA` / `_WORKSPACE` / `_V3_SETTINGS` |
| HTTP 令牌头 | `X-Gate-Token` | `X-BuildChoice-Token` |
| 分类器协议与契约文件 | `gate.v1` / `gate-v1.schema.json` | `buildchoice.v1` / `buildchoice-v1.schema.json` |
| V3 临时句柄前缀 | `cg-v3-ctx-` | `buildchoice-v3-ctx-` |

工具全名也随服务键变化，例如 `mcp__buildchoice__buildchoice_evaluate`。Hook 匹配器、原生设置工具和 Skill 已同步更新。审计 `audit.v1` 与决策 `decision.v3` 的数据结构及 SQLite 表名保持原有含义。

GitHub 托管地址目前仍为 `a853255726-liu/change-note`。README 使用该有效地址并将克隆目录指定为 `BuildChoice`；程序标识已统一。仓库在 GitHub 设置中改名后，再同步更新克隆 URL。

## 旧安装与账本

1. 停止旧 worker，结束待答卡片，关闭旧插件，避免两套 Hook 同时处理消息。
2. 备份项目的完整 `.gate_audit` 目录，包括数据库与已有备份。停止写入后，将完整目录复制到同一项目的 `.buildchoice_audit`；目标已存在时先检查双方内容，不要直接覆盖。
3. 按 README 使用新初始化入口安装 `buildchoice`。默认创建新的 `~/.buildchoice`；不要直接复用指向旧包与旧脚本的 `binding.json`。
4. 若使用自定义数据目录或环境变量，改为新的名称并重新初始化。手动核对调用模式与 V3 设置，新安装保持 Prompt-first、V3 关闭、模型检查关闭。
5. 查看账本历史并开启新会话。旧会话句柄和 worker 回执不迁移为新的用户确认；已有确认历史保留在复制的账本中。

安装器不会自动移动旧数据或修改宿主 Hook 信任。旧目录仍被 Git 忽略并排除在证据采集之外。`migration.migrate_text` 专门识别旧版手工注册，因此其中保留旧服务键和脚本名。

## 本地小判别模型

NLI 基座、LoRA 权重、输入投影、分数计算与阈值规则未因改名而调整，仓库仍不附带模型权重。

旧冻结运行时可以作为独立旧版本保留，其配置和哈希清单应保持匹配。新 BuildChoice worker 使用新包名、`[buildchoice]` 配置段与 `buildchoice.v1` 协议；部署时需依据实际资源重新生成清单中的源码路径与 SHA256，不能只替换旧清单里的文字。

V3 的 `model_runtime` 可继续指向完整、独立的旧冻结运行时；桥接脚本识别旧包名并调用该运行时自身的请求构造与推断实现。它不改写旧配置或模型清单。迁移到新运行时前应另外验证实际模型调用；名称与打包检查不代表模型效果验证。
