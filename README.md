# Clarification Gate

Clarification Gate 是一个给 Codex 用的本地插件，处理编程任务里那些还没说清楚、但会影响产品实际行为的选择。

比如给笔记应用增加分享链接。Codex 可以写出“拿到链接就能看”和“仅受邀用户能看”两种实现，但访问范围最好先由使用者决定。Clarification Gate 会结合当前需求和项目文件，找出类似的问题，在原来的对话里说明不同选项，再让 Codex 继续写代码。

普通开发任务仍按原来的方式执行，不必为每个技术细节停下来讨论。

## 使用示例

用户提出：

> 给我的笔记应用增加分享链接。

当访问范围还没有确定时，Codex 可以在对话里显示：

```text
Clarification Gate · 决策 1/1

分享链接应该允许谁查看笔记？
这会影响分享功能的访问权限。

A. 知道链接的人都可以查看
   分享方便，但链接转发后其他人也能访问。

B. 只有指定用户可以查看
   需要登录和权限检查，适合不公开的内容。

回复 A / B，也可以先讨论两种方式的区别。
```

在受信任 Hook 可用的环境中，用户的选项回复会与当前决策绑定并记录，供后续实现参考。没有需要确认的选择时，不显示决策卡。

## 安装

需要 Python 3.11+ 和支持本地插件的 Codex 环境。当前决策卡功能位于 `feat/decision-discovery-v3` 分支。

```bash
git clone https://github.com/a853255726-liu/change-note.git
cd change-note
git switch feat/decision-discovery-v3

python plugins/clarification-gate-controls/setup.py \
  --workspace /absolute/path/to/your-project \
  --runtime-root . \
  --install
```

在 Windows PowerShell 中可使用单行命令：

```powershell
python plugins/clarification-gate-controls/setup.py --workspace "C:\\path\\to\\your-project" --runtime-root . --install
```

安装器会准备本地 Python 环境。Codex 的 Hook 需要按宿主提示进行信任确认，安装器不会代为修改审批设置。

安装后默认使用轻量的 Prompt-first 澄清策略。要开启对话决策卡，在仓库目录执行：

```bash
python scripts/gate_decisions.py pilot
```

查看设置或关闭决策卡：

```bash
python scripts/gate_decisions.py settings
python scripts/gate_decisions.py off
```

决策卡不依赖额外的分类模型。模型校验默认关闭。

## 工作方式

插件通过一个 Skill 引导 Codex 查阅相关项目资料并整理候选选择。MCP 工具负责检查候选和已有证据，决定是先查文件、现在询问、稍后处理，还是直接继续。需要询问时，一次只展示一张卡。

确认记录保存在当前项目的 `.gate_audit/ledger.sqlite3`。记录与当前会话、选项及版本关联；用户要求解释或给出自由回答时，不会被直接当作已经确认。决策发生变更时保留旧版本，便于检查后续实现是否需要调整。

插件还保留了独立的决策证据审计工具，可以读取项目文件、关联引用并导出记录。它也可以单独使用：

```bash
python scripts/gate_audit.py --workspace /absolute/path/to/your-project serve
```

本地记录不会由插件自动上传。对话决策卡不替代 Codex 自身的文件、网络或命令执行审批。

## 文档

- [决策卡使用说明](docs/DECISION_GUIDANCE.md)
- [架构](docs/ARCHITECTURE.md)
- [MCP 与数据接口](docs/API.md)
- [本地模型接入](docs/MODEL_BACKEND.md)
