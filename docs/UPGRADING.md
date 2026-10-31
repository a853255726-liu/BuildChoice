# BuildChoice · 升级说明

## 升级到 0.8.3

更新运行时、重新安装插件并重新连接 MCP（或重启 Codex），停止旧版服务再使用新恢复流程。没有数据库表结构迁移，旧任务、确认、快照和事件保留；不把历史未核验记录改为已确认。

新消息摘要只统一换行符及首尾空行，正文空格和缩进仍参与校验。旧记录可按原文或常见末尾单换行形式匹配，不改写原摘要；无法匹配的旧消息应保留原文或建立新范围。

已完成的旧筛选缓存缺少当前状态快照，会返回 CACHED_SCREEN_STALE；重新读取相关来源和状态，用新幂等键筛选。旧版遗留的未完成标记只有在请求摘要匹配、取得写锁后才恢复；摘要不匹配时保留记录并使用新键。新筛选失败整体回滚，不留下新的半成品标记。同一任务的连接句柄和 task_id 不计入新筛选请求的语义指纹，但每次请求仍先核验当前句柄、会话和任务归属。

## 升级到 0.8.2

修复旧激活缓存重放与 Windows Python 3.11 目录联接过滤。更新运行时并重新安装插件后重新连接 MCP（或重启 Codex），保留现有开关、确认和事件历史，无数据库迁移。

失效的激活重试现在返回错误。先读取当前任务状态，按需要用新的幂等键重新激活有效决定；不要把旧缓存文本当成当前卡片。正常的同卡重试仍返回原结果且不续期。Windows 路径检查使用 Python 3.11 已支持的 lstat/reparse tag，不依赖 3.12 新增的 Path.is_junction。

## 升级到 0.8.1

修复工具列表刷新、过期待答占用、新任务范围绑定和 Hook 自检。更新运行时并重新安装插件，再重新连接 MCP（或重启 Codex）以加载新的服务代码与 Skill。更新后的连接在原生设置或 CLI 开关改变工具可见性时发送刷新通知；宿主需支持 MCP 工具列表变更通知。

没有数据库迁移，不改写旧确认或测试结论。过期卡和切换任务前的旧卡仍保持未确认；恢复相关工作时重新激活并展示后再等待用户明确回复。安装继续遵守宿主 Hook 信任流程，不自动授予信任。

## 升级到 0.8.0

新增两个 MCP 工具、显式测试采集 CLI 和两份契约，使用现有 V3 事件及幂等操作表，无新表或数据库版本迁移。旧任务的 verification 字段为空，不会自动生成验收或回填通过结果。旧确认和 audit.v1 历史保持原含义；回退仍保留 audit.v1。

更新运行时并重新初始化/安装插件以刷新 Skill 与工具缓存。新运行包包含采集入口、内部 worker 和契约，doctor 检查它们是否齐全。默认依赖不含浏览器测试组件；仅运行浏览器示例时另装 requirements-dev.txt。全局 off 与 V3 off 禁用新增 MCP 能力；显式采集 CLI 也检查这两个开关。网页仍只展示 audit.v1。

详见 [决策落实验证](DECISION_VERIFICATION.md)。本地记录属于同一用户信任边界，不防御有权修改 SQLite、运行时或测试代码的恶意本地进程。

## 升级到 0.7.0

新增 `scripts/buildchoice_doctor.py` 和 `buildchoice_link_implementation`。前者只读检查本地环境，可加 --host 查询宿主插件和 Hook 声明；没有独立确认的状态显示未验证。不会修改审批、Hook 信任或安装配置。

实现关联复用 V3 事件表，不改变数据库版本或已有记录。任务状态新增 implementations 字段，记录 Agent 登记的真实文件位置和哈希，并在决定版本或文件变化时提示待复核。保留旧事件，不宣称实现正确性已经独立验证。

网页继续作为可选 audit.v1 审计入口，不是新增功能的必需部分。更新源码或换用新运行包后重新安装插件，以刷新缓存中的工具、Skill 和 Hook；初始化方式不变。

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
