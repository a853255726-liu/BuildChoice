# BuildChoice

**让 AI 编程中的关键产品选择，由用户来决定。**

BuildChoice 是一款面向 Codex 的本地 AI 编程插件，帮助使用 AI 开发应用的用户掌握重要的产品决策。用户往往只描述想实现的功能，却未必知道背后存在多种会影响体验、数据、权限或成本的实现方案。如果 Agent 擅自选择，最终做出来的产品可能与用户预期不同。

BuildChoice 在开发过程中结合用户需求和现有项目资料，识别真正需要用户决定的实现选择，解释不同方案的影响，并将用户的决定保留下来，供后续开发沿用。普通技术细节由 Codex 自行处理，减少不必要的提问。

## 核心功能

- **主动发现关键选择**：通过 Agent + Skill 的结构化检查、场景化提示和项目资料读取，寻找影响实际产品行为的未明确决策。
- **按需追问与方案解释**：MCP 将候选分为 `ASK_NOW / INSPECT / DEFER / PROCEED`，优先读取已有信息；确需决定时，在原对话中逐项展示方案、利弊与建议。
- **确认与实现关联**：通过 Codex Hook 关联用户在当前会话中的选项回复，记录决策版本及相关代码位置，方便需求修改与后续调整。
- **项目决策记忆**：在同一项目的不同聊天中检索已有选择，支持长期规则、普通参考自动归档，以及遗忘、恢复和冲突处理。
- **决策落实检查**：将已确认的选择整理为可执行的行为要求，并结合相关代码和测试结果，帮助核对实际实现是否符合用户选择。

## 使用示例

用户提出：

> 帮我做一个记账小程序，支持拍照识别购物小票，自动提取消费金额、日期和类别。

如果原需求和项目资料没有指定入账方式，BuildChoice 可以提出：

```text
BuildChoice · 关键实现选择

识别出小票信息后，应该直接保存，还是让用户先核对？

A. 自动保存
   步骤更少，但错误金额或类别可能直接进入账本。

B. 核对后保存（推荐）
   可以修改识别结果再保存，多一步操作但更容易避免错账。

回复 A / B，也可以先讨论两种方案的区别。
```

用户选择后，Codex 按确定的方向继续开发。BuildChoice 保存选择及其来源，后续修改功能时可参考原决定，遇到新的冲突再与用户确认。

## 工作原理

```text
用户需求 + 项目资料
        ↓
Agent + Skill 识别候选选择
        ↓
MCP 检查证据与当前开发依赖
        ↓
需要决定 → 决策卡 → 用户确认
无需决定 → 直接继续开发
        ↓
记录决策、关联实现、项目内复用
```

插件不需要单独部署分类模型。核心组件包括 Codex Skill、MCP、UserPromptSubmit Hook、SQLite 本地账本与可选的代码落实检查功能。默认使用轻量的 Prompt-first 策略，决策卡可独立开启。

## 安装

需要 Python 3.11+、Git 和支持本地插件的 Codex。将 `--workspace` 替换为**已经存在**的项目目录。

```bash
git clone https://github.com/a853255726-liu/change-note.git BuildChoice
cd BuildChoice

python plugins/buildchoice/setup.py \
  --workspace /absolute/path/to/your-project \
  --runtime-root . \
  --install

python scripts/buildchoice_decisions.py pilot
```

Windows PowerShell 可以使用单行命令：

```powershell
python plugins/buildchoice/setup.py --workspace "C:\\path\\to\\your-project" --runtime-root . --install
python scripts/buildchoice_decisions.py pilot
```

安装器会准备本地运行依赖。Codex 的 Hook 信任由宿主按原有流程确认，不会被插件自动修改。

运行模式：

```bash
python scripts/buildchoice_decisions.py settings  # 查看决策卡设置
python scripts/buildchoice_decisions.py pilot     # 开启决策卡
python scripts/buildchoice_decisions.py off       # 关闭决策卡
```

本地记录位于项目的 `.buildchoice_audit/ledger.sqlite3`，不会由插件自动上传。BuildChoice 不替代 Codex 的文件、网络和命令权限审批。

## 详细文档

- [决策卡使用说明](docs/DECISION_GUIDANCE.md)
- [项目决策记忆](docs/DECISION_MEMORY.md)
- [决策与代码关联](docs/ARCHITECTURE.md)
- [决策落实功能](docs/DECISION_VERIFICATION.md)
- [安装与升级](docs/UPGRADING.md)
- [MCP 接口](docs/API.md)
