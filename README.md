# BuildChoice

[![CI](https://github.com/a853255726-liu/BuildChoice/actions/workflows/integration.yml/badge.svg)](https://github.com/a853255726-liu/BuildChoice/actions/workflows/integration.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**让 AI 编程中的关键产品选择，由用户来决定。**

BuildChoice 是一款面向 Codex 的本地 AI 编程插件，帮助使用 AI 开发应用的用户掌握重要的产品决策。用户往往只描述想实现的功能，却未必知道背后存在多种会影响体验、数据、权限或成本的实现方案。如果 Agent 擅自选择，最终做出来的产品可能与用户预期不同。

BuildChoice 在开发过程中结合用户需求和现有项目资料，识别真正需要用户决定的实现选择，解释不同方案的影响，并将用户的决定保留下来，供后续开发沿用。普通技术细节由 Codex 自行处理，减少不必要的提问。

## 核心功能

- **产品后果与工程取舍**：从数据恢复、协作冲突、性能、扩展、可靠性、迁移、锁定和维护成本等角度解释不同方案的影响；普通低风险工程细节由 Codex 自主处理，高风险选项可附有依据的风险提示。
- **主动发现关键选择**：通过 Agent + Skill 的结构化检查、场景化提示和项目资料读取，寻找影响实际产品行为的未明确决策。
- **按需追问与方案解释**：MCP 将候选分为 `ASK_NOW / INSPECT / DEFER / PROCEED`，优先读取已有信息；确需决定时，在原对话中逐项展示方案、利弊与建议。
- **确认与可选代码关联**：通过 Codex Hook 记录用户选择和版本；有追溯需要时，为真实已确认的决策关联文件位置及哈希，不要求每次开发登记。
- **项目决策记忆**：在同一项目的不同聊天中检索已有选择，支持长期规则、普通参考自动归档，以及遗忘、恢复和冲突处理。遗忘会停止主动召回，历史记录仍保留。
- **原生测试**：测试、验收与解释交给 Codex，BuildChoice 不作为需求正确性的独立认证。
- **真实资料读取记录**：PostToolUse 对受支持工具自动核验返回的文件内容与范围，优先供 INSPECT 使用；不能识别时回退审计读取器，不保存工具输出正文。见[支持范围](docs/PROJECT_READS.md)。

## 在提示词之外增加了什么

提问、方案解释和开发测试仍由 Codex 执行。BuildChoice 将其中的重要选择保存成可查询、可修订的记录，并用服务端规则检查确认和证据是否仍然适用。

| 在对话中提出的要求 | BuildChoice 提供的记录与检查 |
|---|---|
| 遇到重要选择先询问 | 根据证据与开发依赖进行四状态分流，同一会话一次激活一张卡 |
| 记住用户选了什么 | 将 Hook 观察到的选项回复绑定到具体决策和版本，保留确认来源 |
| 修改需求后沿用正确方案 | 追加修订，保留原选择，提示关联代码需要复核 |
| 下次聊天继续参考 | 项目内检索已确认选择，区分普通参考、长期规则、归档与遗忘 |
| 检查代码是否落实选择 | 由 Codex 原生测试并解释结果；可选关联只用于定位 |

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

回复 A / B、“我选第二个”或完整方案名称，也可以先讨论两种方案的区别。
```

用户选择后，Codex 按确定的方向继续开发。BuildChoice 保存选择及其来源，后续修改功能时可参考原决定，遇到新的冲突再与用户确认。

长期记忆由独立 [decision-memory Skill](plugins/buildchoice/skills/decision-memory/SKILL.md) 管理。直接说“把刚才的选择长期记住”或“把人工核对设为项目默认规则”，目标明确时直接保存，无需输入编号或再次确认。只有真实 Hook 指令经过 MCP 核验才能升级；目标有歧义时澄清。普通选择默认作参考，30 天归档，不主动追问长期保存；长期规则持续有效，支持修订、冲突处理和遗忘。见[决策记忆](docs/DECISION_MEMORY.md)。

## 工作原理

候选提取前先按相关行为与后果检索历史，在 Codex 原有推理中区分同义、相关、冲突与范围不同；相似不等于可复用。MCP 检查稳定身份、范围、版本、文件哈希与引用，将自然语言解释和结构化约束分开。证据不充分或发现可能漏掉的风险时先补查；零候选不证明没有风险。详见[候选校验与工程风险](docs/CANDIDATE_RISKS.md)。

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

核心组件包括 Codex Skill、MCP、UserPromptSubmit / PostToolUse Hook 与 SQLite 本地账本。默认使用轻量的 Prompt-first 策略，决策卡可独立开启，代码关联按需使用。

## 名称与运行模式

- **0.10.1** 是当前源码版本。
- **决策卡模式**在配置和技术文档中称为 V3，开启命令是 pilot；它是功能开关，不是产品版本号。
- **Prompt-first** 是默认的澄清提示策略；完整决策卡流程需另行开启。
- **.claude-plugin** 是本地插件市场的兼容目录，当前安装器通过 Codex app-server 注册和加载插件，不需要启动另一个编程助手。见[架构说明](docs/ARCHITECTURE.md#名称与兼容目录)。

## 安装

需要 Python 3.11+、Git 和支持本地插件的 Codex。将 `--workspace` 替换为**已经存在**的项目目录。

```bash
git clone https://github.com/a853255726-liu/BuildChoice.git
cd BuildChoice

python plugins/buildchoice/setup.py \
  --workspace /absolute/path/to/your-project \
  --runtime-root . \
  --decision-mode pilot \
  --install

```

Windows PowerShell 可以使用单行命令：

```powershell
python plugins/buildchoice/setup.py --workspace "C:\path\to\your-project" --runtime-root . --decision-mode pilot --install
```

安装器会准备本地运行依赖。Codex 的 Hook 信任由宿主按原有流程确认，不会被插件自动修改。

安装并启用后，在 Codex 对话中提出开发需求，BuildChoice 随相关任务工作。

运行模式：

```bash
python scripts/buildchoice_decisions.py settings  # 查看决策卡设置
python scripts/buildchoice_decisions.py pilot     # 开启决策卡
python scripts/buildchoice_decisions.py off       # 关闭决策卡
```

安装器将生成的 MCP、Hook 和项目配置保存在独立数据目录，源码 checkout 的配置文件保持不变。每个项目保存独立绑定和运行设置。

查看已绑定项目，或切换到已有项目：

~~~bash
python plugins/buildchoice/setup.py --list-projects
python plugins/buildchoice/setup.py --use-project /absolute/path/to/project
~~~

新连接优先按当前项目目录匹配绑定；显式切换后重新连接 MCP。已打开的连接继续使用原绑定。详见[项目使用与切换](docs/PROJECTS.md)。

本地记录位于项目的 `.buildchoice_audit/ledger.sqlite3`，不会由插件自动上传。BuildChoice 不替代 Codex 的文件、网络和命令权限审批。

## 发布与许可

可在源码目录运行 `python scripts/build_distribution.py` 生成核心运行包、插件包与 SHA256 校验文件；安装方式见[升级说明](docs/UPGRADING.md)。项目采用 [MIT License](LICENSE)。

## 详细文档

- [决策卡使用说明](docs/DECISION_GUIDANCE.md)
- [项目决策记忆](docs/DECISION_MEMORY.md)
- [决策与代码关联](docs/ARCHITECTURE.md)
- [安装与升级](docs/UPGRADING.md)
- [MCP 接口](docs/API.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [开发与测试](docs/VALIDATION.md)
