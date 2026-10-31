# BuildChoice

**让用户决定 AI 编程中的关键产品行为，并检查决定是否落实。**

BuildChoice 是面向 Codex 的本地 AI 编程插件，重点服务不熟悉技术实现、但需要把控产品行为的开发者。面对模糊的开发需求，它先阅读当前项目约束，通过 Agent + Skill 提取会影响功能、数据、权限或费用的重要实现选择；只有当前确实需要用户决定时，才展示附有方案、影响与建议的决策卡。普通工程细节由 Codex 自行处理。

用户确认后，BuildChoice 记录决定与版本，关联实现文件，并按需将选择转为行为验收条件、采集实际执行的测试结果。0.9 新增**项目决策记忆**：在同一项目的后续聊天中检索已确认选择，支持长期规则、30 天普通参考归档、遗忘与恢复。所有记录默认保存在本地工作区。

## 使用示例

用户提出：

> 帮我做一个记账小程序，支持拍照识别购物小票，自动提取消费金额、日期和类别。

在项目资料没有规定入账流程时，BuildChoice 可以展示：

```text
BuildChoice · 关键实现选择

识别出小票后，是直接保存账目，还是先让用户核对？

A. 自动保存
   操作更快，但识别错误可能直接进入账本。

B. 核对后保存（推荐）
   用户可以修改金额、日期和类别再保存，多一步操作但更容易避免错账。

回复 A / B，也可以先讨论两种方案的区别。
```

选定方案后，Codex 继续开发。BuildChoice 保存当前决定与版本；需要时可登记相关实现文件，并通过实际执行的行为测试核对已声明的验收条件。后续开发可参考该项目已有决定，遇到适用范围变化或冲突时重新核实。

上面是示意交互，实际提问以当前需求与项目约束为准。

## 主要能力

- **关键决策发现与低打扰筛选**：五类候选检查范围、四道判断门槛、按开发场景选择检查视角；服务端按 `ASK_NOW / INSPECT / DEFER / PROCEED` 分流，先查项目证据，再决定是否需要打断。
- **可解释决策卡与可信确认**：提供方案利弊与建议；由 Codex 的 `UserPromptSubmit` Hook 关联真实选项回复，支持解释、暂缓、版本修订和历史追溯。
- **实现关联及行为验证**：记录关联的真实代码文件和哈希；根据已确认选择生成验收条件，显式执行项目行为测试，保留执行证据并识别结果失效。
- **项目决策记忆**：已确认选择形成项目内参考，支持跨聊天检索、长期规则、30 天归档、遗忘与恢复；旧记忆不自动赋予新任务操作许可。
- **本地优先与可控开关**：默认 Prompt-first，可单独开启决策卡；不需要额外训练或部署分类模型，保留 Codex 原有文件、网络和命令权限审批。

## Windows PowerShell 安装

需要 Python 3.11+、Git 和支持本地插件的 Codex。先创建或选定要使用的**现有项目目录**（`--workspace` 必须指向已存在的目录）：

```powershell
git clone https://github.com/a853255726-liu/change-note.git BuildChoice
cd BuildChoice

python plugins/buildchoice/setup.py --workspace "C:\\path\\to\\your-project" --runtime-root . --install
python scripts/buildchoice_decisions.py pilot
python scripts/buildchoice_doctor.py --host --json
```

安装器准备本地依赖并注册插件。Hook 信任由 Codex 按正常审批流程确认，安装器不会自动修改宿主权限。

Linux/macOS 安装时同样从仓库根目录运行 `setup.py`，将 `--workspace` 改为实际的绝对路径。

## 运行模式

```bash
python scripts/buildchoice_decisions.py settings   # 查看决策卡状态
python scripts/buildchoice_decisions.py pilot      # 启用 V3 决策引导
python scripts/buildchoice_decisions.py off        # 关闭 V3 决策引导
python scripts/buildchoice_settings.py status      # 查看全局运行模式
```

- **Prompt-first** 为默认澄清策略；决策卡需独立开启。
- **V3 决策卡** 根据当前开发任务和项目资料按需出现，不设追问数量配额。
- **项目账本** 位于工作区 `.buildchoice_audit/ledger.sqlite3`。本地记录不会由插件自动上传。
- **实现验证** 需要在原有授权下显式运行行为测试，静态文件关联不等于测试通过。

## 测试与文档

项目包含单元回归、真实 STDIO MCP 协议检查、源码/打包检查、跨平台路径边界检查及浏览器行为正反例。最新执行记录和具体测试范围参见 [验证记录](docs/VALIDATION.md)。

- [项目决策记忆与遗忘](docs/DECISION_MEMORY.md)
- [决策卡使用说明](docs/DECISION_GUIDANCE.md)
- [决策落实验证](docs/DECISION_VERIFICATION.md)
- [架构](docs/ARCHITECTURE.md)
- [测试与复现指南](docs/END_TO_END_TESTING.md)
- [安装升级](docs/UPGRADING.md)
- [MCP 与数据接口](docs/API.md)
