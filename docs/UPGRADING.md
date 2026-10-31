# BuildChoice · 升级说明

## 升级到 0.10.0

重新运行 setup.py，为已有项目生成独立插件副本与项目绑定，然后执行 --install 并重新连接 MCP。安装器不再重写源码中的 MCP、Hook 或市场配置。旧 binding.json 可以读取；注册新项目时会保留旧绑定。

同一数据目录可添加多个项目，使用 --list-projects 查看、--use-project 路径切换。各项目的运行设置保存在自己的 configs 目录；账本仍留在项目目录。详细命令见[项目指南](PROJECTS.md)。

当前确认支持明确的字母、序号及完整方案名称表达。集成可提供 decision_key 与 option_key，使任务间改写显示文字后仍可定位同一规则。旧候选请求继续可用，无 SQLite 表结构迁移。

## 升级到 0.9.1

0.9.1 将安装与使用入口统一为 Codex 插件，移除独立审计网页、根目录 START.cmd、审计 CLI 和早期手工注册清理函数。账本、文件证据、兼容审计 MCP、决策、记忆及验证接口保持可用，无数据库结构迁移。

原来使用独立网页的用户可在 Codex 中通过证据和审计工具查询记录、导出报告。更新不会删除现有 SQLite 数据。当前核心运行包只包含 Python 运行时、契约和配置，不再分发网页资源。

### 源码安装

1. 停止使用旧版 MCP 服务，备份目标项目的 .buildchoice_audit 目录。
2. 更新源码，并按 README 重新运行 setup.py --workspace 目标项目 --runtime-root . --install。
3. 重连 MCP 或重启 Codex，运行 doctor；Hook 信任按宿主提示审阅。

### 运行包安装

保留旧运行包、安装绑定和项目账本，以独立 --data-home 初始化新版本核心包后再安装插件。安装器不会覆盖已有运行目录中的文件；不要将新 ZIP 直接解压到正在使用的安装中。

检查新绑定指向正确项目、Python 和运行时，再确认插件启用和已有开关。使用方式见[README](../README.md)，诊断见[故障排查](TROUBLESHOOTING.md)。

## 从较早版本升级

| 原版本 | 需要了解的变化 |
|---|---|
| 0.9.0 | 项目记忆语义不变：普通参考 30 天归档，长期规则需明确标记，遗忘保留历史 |
| 0.8.x | 已确认选择可进入普通参考；按原确认时间计算归档，不把未确认历史升级为确认 |
| 0.7.x | 新增行为验收与显式测试采集；旧实现关联不自动变成通过结果 |
| 0.6.x 及更早 | 当前不提供小判别模型、推理服务或旧分类器调用模式；旧模型事件只保留历史含义 |

旧筛选缓存缺少当前快照时会返回 CACHED_SCREEN_STALE。重新读取相关来源与任务状态，用新幂等键筛选；旧确认、消息摘要、实现关联和验证历史保持原义。

## 早期名称与注册

早期版本使用 clarification_gate / clarification-gate-controls 和 .gate_audit。迁移账本前先完整备份；新目录已有数据时不要覆盖。旧目录仍被证据读取器排除。

0.9.1 不再自动清理早期手工注册。使用过旧注册方式的用户，应先在 Codex 配置中核对并停用对应旧服务和 Hook，再按当前安装流程重新初始化。不要复用仍指向旧脚本的 binding.json。

当前托管地址为 [a853255726-liu/BuildChoice](https://github.com/a853255726-liu/BuildChoice)。已有 checkout 可将 origin 更新到该地址。

## 数据迁移与回退

通常只需关闭决策卡，无须删除数据。首次建立决策表时会备份 SQLite；已有 audit.v1 数据保留。

确需移除决策表时，先关闭试用并停止相关会话，再执行：

~~~bash
python scripts/buildchoice_decisions.py off
python scripts/buildchoice_decisions.py --workspace /absolute/project rollback
~~~

回退会先保存完整备份，再移除决策表，保留 audit.v1。该操作会使当前决策、记忆和验证记录从活动数据库中移除；恢复前应停止相关进程并使用完整备份。
