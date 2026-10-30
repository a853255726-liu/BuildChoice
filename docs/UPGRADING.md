# BuildChoice · 升级说明

## 升级到 0.6.0

本版本移除小判别模型、NLI/LoRA 后端、推理 worker、模型清单接入、模型依赖、buildchoice.v1 推断协议及分类器控制面板。原来的模型调用、强制评估和自动调用工具不再提供。保留 Prompt-first、audit.v1 和 decision.v3。

- 运行模式仅为 Prompt 优先 / 完全关闭，配置使用 `configs/buildchoice.json`；CLI 为 `scripts/buildchoice_settings.py`。旧 required / auto 模式不再存在。
- V3 设置使用 config_version=2，仅保留 mode 与 context_ttl_seconds。旧 config_version=1 可读取，旧模型开关与运行时路径被忽略，显式写设置时转为新版。
- 安装器不再接受 `--with-classifier`、`--device` 或 worker `--port`；运行包不包含模型依赖。
- 插件仅注册 UserPromptSubmit，Hook 入口为 `scripts/buildchoice_hook.py`。重新安装后按宿主正常流程审阅 Hook 信任。
- 候选筛选新增可选 coverage，当前响应不再含 model_status / model_fields / model_diagnostics。旧筛选请求仍可接受，覆盖状态显示 reported=false。

更新前停止旧 worker、结束待答卡并关闭旧插件。保留旧安装和完整 `.buildchoice_audit` 备份，在新运行时目录或源码 checkout 重新初始化。旧 bundle 安装不要直接覆盖运行时；选择新的 data-home。根据需要重新选择运行模式和 V3 开关，新安装默认 Prompt-first、V3 关闭。

账本沿用原 SQLite 表结构，覆盖记录复用事件表。旧确认、审计和模型事件保留为历史，不删除、不重新解释为新的确认。工具当前返回会省略已移除的模型字段。升级不会删除用户本机单独部署的模型文件、其他环境依赖或工作区数据。

## 0.5.0 名称变更

| 项目 | 旧名称 | BuildChoice 名称 |
|---|---|---|
| Python 包 | clarification_gate | buildchoice |
| 插件安装 ID | clarification-gate-controls | buildchoice |
| 本地市场 | clarification-gate-local | buildchoice-local |
| MCP 服务键 | clarification_gate | buildchoice |
| 工具前缀 | gate_ | buildchoice_ |
| 安装数据 | ~/.clarification-gate | ~/.buildchoice |
| 项目账本 | .gate_audit | .buildchoice_audit |

从 0.4.x 升级时，先停止写入并备份整个旧账本目录，再复制到同一项目的新账本目录；目标已存在时不要直接覆盖。新安装需重新初始化，不复用指向旧脚本的 binding.json。旧目录继续被 Git 忽略并排除在证据采集之外。migration.migrate_text 保留旧名称，仅识别旧手工注册以便受限迁移。

GitHub 托管地址目前仍为 `a853255726-liu/change-note`；README 将克隆目录指定为 BuildChoice。仓库设置改名后应同步克隆 URL。
