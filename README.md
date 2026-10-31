# BuildChoice

BuildChoice 是一个用于 Codex 的本地插件。遇到会影响产品实际行为的实现选择时，它会先检查需求和项目文件；确实需要用户决定的部分，再通过对话说明可选方案。

比如开发一个拍照记账小程序：识别出小票上的金额和类别后，是直接写入账本，还是先让用户核对？两种方式都能实现，但使用流程和出错后的处理不同。这类选择适合交给用户，普通技术细节则由 Codex 自行处理。

## 使用示例

用户提出：

> 帮我做一个记账小程序，支持拍照识别购物小票，自动提取消费金额、日期和类别。

如果需求和项目资料都没有说明识别结果如何入账，Codex 可以在对话中提出这样的选择：

```text
BuildChoice · 决策 1/1

识别完小票后，要直接保存账目，还是先让用户核对？
如果金额或类别识别有误，直接保存会影响之后的消费统计。

A. 自动保存
   识别后直接生成记录，操作更快。
   但识别错误也可能直接进入账本，需要事后修改。

B. 核对后保存（推荐）
   先显示识别出的金额、日期和类别，用户可以修改后再保存。
   多一步操作，但能及时发现错账。

建议 B：这些数据会用于后续统计，保存前核对通常更稳妥。

回复 A / B，也可以先讨论两种方式的区别。
```

这是示意对话。用户选定方案后，在受信任 Hook 可用的环境中，插件会将回复与当前决策及版本关联记录，供后续开发参考。没有需要确认的选择时，不显示决策卡。

## 安装

需要 Python 3.11+ 和支持本地插件的 Codex 环境。

```bash
git clone https://github.com/a853255726-liu/change-note.git BuildChoice
cd BuildChoice

python plugins/buildchoice/setup.py \
  --workspace /absolute/path/to/your-project \
  --runtime-root . \
  --install
```

在 Windows PowerShell 中可使用单行命令：

```powershell
python plugins/buildchoice/setup.py --workspace "C:\\path\\to\\your-project" --runtime-root . --install
```

安装器会准备本地 Python 环境。Codex 的 Hook 需要按宿主提示进行信任确认，安装器不会代为修改审批设置。

安装后默认使用轻量的 Prompt-first 澄清策略。要开启对话决策卡，在仓库目录执行：

```bash
python scripts/buildchoice_decisions.py pilot
```

查看设置或关闭决策卡：

```bash
python scripts/buildchoice_decisions.py settings
python scripts/buildchoice_decisions.py off
```

BuildChoice 不包含小判别模型、模型 worker 或模型依赖。候选由当前 Agent 提取，服务端通过项目证据与确定性规则分流。

## 安装自检

```powershell
python scripts/buildchoice_doctor.py
python scripts/buildchoice_doctor.py --host --json
```

默认检查本地绑定、目标项目、Python 依赖、运行时入口和独立 MCP 启动；`--host` 额外通过只读接口检查插件启用与 Hook 信任声明。没有取得的状态显示“未验证”，不会自动安装、改配置或信任 Hook。独立 MCP 启动不证明宿主已加载插件，信任定义也不证明实际聊天回调已经执行。

## 工作方式

V3 开启时，工作区内的用户消息会取得短期 Hook 句柄；是否正在开发由 Codex 结合本轮消息与对话上下文判断。短句和承接请求不会因为正则未命中被排除，普通咨询仍直接回答。

插件通过一个 Skill 引导 Codex 查阅相关项目资料并整理候选选择。MCP 工具负责检查候选和已有证据，决定是先查文件、现在询问、稍后处理，还是直接继续。需要询问时，一次只展示一张卡。

Agent 在同一次候选提取中附上简短的覆盖依据，说明相关维度已有答案、形成候选、不适用或仍不确定。服务端核对引用并保存记录，不增加第二轮复核；覆盖记录不证明没有遗漏，也不单独触发问题。

确认记录保存在当前项目的 `.buildchoice_audit/ledger.sqlite3`。记录与当前会话、选项及版本关联；用户要求解释或给出自由回答时，不会被直接当作已经确认。决策发生变更时保留旧版本，便于检查后续实现是否需要调整。

完成实现时，Agent 可顺带将决定关联到真实代码文件和行号，服务端保存文件哈希。决定修订或文件变化后，关联显示待复核；文件关联是 Agent 登记，不证明代码已正确满足决定。

0.8 增加可选的决策落实验证：将当前已确认的选择整理为 Agent 推导的验收条件，显式运行已授权的行为测试，再通过 MCP 保存逐项结果。没有实际测试不能通过；决定、验收条件、声明的代码/测试/配置或执行环境发生变化后，旧通过结果显示失效。条件推导不是新的用户授权，静态代码引用不能替代行为测试。见 [决策落实验证](docs/DECISION_VERIFICATION.md)。

插件还保留了独立的决策证据审计工具，可以读取项目文件、关联引用并导出记录。它是可选的本地网页入口，不是插件运行的必需部分。目前网页展示 audit.v1 审计账本、证据快照、复核和导出；V3 聊天选择及实现关联通过 MCP 查询。网页可单独使用：

```bash
python scripts/buildchoice_audit.py --workspace /absolute/path/to/your-project serve
```

本地记录不会由插件自动上传。对话决策卡不替代 Codex 自身的文件、网络或命令执行审批。

可通过 `python scripts/buildchoice_settings.py status` 查看运行模式；`off` 完全关闭提示、MCP 审计与决策卡，`prompt` 恢复 Prompt-first。独立启动的审计 CLI/网页仍由使用者显式操作。

## 文档

- [决策卡使用说明](docs/DECISION_GUIDANCE.md)
- [决策落实验证与示例](docs/DECISION_VERIFICATION.md)
- [名称与升级说明](docs/UPGRADING.md)
- [验证方法与范围](docs/VALIDATION.md)
- [集成、真实 Codex 宿主验收与产品效果测试](docs/END_TO_END_TESTING.md)
- [架构](docs/ARCHITECTURE.md)
- [MCP 与数据接口](docs/API.md)
