# BuildChoice 更新记录

## 0.5.0 · 统一项目名称

- Python 包、插件 ID 和 MCP 服务键统一为 `buildchoice`，工具使用 `buildchoice_` 前缀。
- 同步调整 CLI、配置、Hook 匹配器、环境变量、HTTP 令牌头、协议标识和打包路径。
- 新安装目录使用 `~/.buildchoice`，项目账本使用 `.buildchoice_audit`；保留对旧账本目录的隐私排除。
- 默认模式、V3 开关和 NLI 推断逻辑不变。旧安装与模型清单需按 [升级说明](docs/UPGRADING.md) 处理。


## 0.4.0 · V3 决策引导试用

新增 `decision-discovery` Skill：主 Agent 发现会改变产品使用方式的重要选择，按当前依赖逐张展示含选项、影响与建议的决策卡。

- 四状态分流：ASK_NOW、INSPECT、DEFER、PROCEED；零候选正常继续。
- 独立的 V3 与 NLI 开关，初始均关闭；模型缺失或不支持时走规则路径。
- UserPromptSubmit 回调关联短期会话句柄；严格选项回复只绑定当前会话的一张有效卡及其版本。
- 修订追加版本，保留旧选择，标记受影响实现待复核。
- V3 使用独立 SQLite 表，首次迁移备份，回退保留 audit.v1 记录。
- 新增四个 MCP 接口和 `scripts/buildchoice_decisions.py` 管理入口。
- 插件与核心包包含新 Skill、契约与运行模块；安装流程延续现有结构。

旧 Prompt-first、审计工作台、CLI、四种判别调用模式及模型接口继续可用。V3 保持试用状态；NLI 建议不替代用户选择或宿主审批。使用步骤见 [V3 使用说明](docs/DECISION_GUIDANCE.md)。
