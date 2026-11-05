# BuildChoice · 安装与更新

更新后重新连接 MCP。未配置 tool_profile 的项目使用日常工具集；需要独立审计或高级功能时，在原生设置切换“工具集：完整”，或执行 `python scripts/buildchoice_decisions.py full`。这不修改既有决定与确认历史。

自定义 MCP 调用方应按当前工具 Schema 提交候选，明确提供 suggested_action；不再提交 needs_user_choice、current_dependency、relevance、engineering_detail 或 why_user_choice。已有 SQLite 记录保持可读，重新提交或修订时使用当前字段。插件与运行时应一并更新，避免使用旧 Skill 生成已退出的字段。

## 从源码安装

需要 Python 3.11+、Git 和支持本地插件的 Codex。先准备已有项目目录，然后在 BuildChoice 仓库根目录执行：

~~~bash
python plugins/buildchoice/setup.py --workspace /absolute/project --runtime-root . --decision-mode pilot --install
~~~

安装器准备 Python 依赖，将插件副本与生成的配置写入安装数据目录，源码配置保持不变。默认数据目录为 ~/.buildchoice，可用 --data-home 指定其他位置。安装后重新连接 MCP 或重启 Codex，按宿主提示审阅 Hook 信任。

## 更新源码安装

1. 停止使用目标项目的 MCP 连接，备份项目的 .buildchoice_audit 目录及安装数据目录。
2. 更新 BuildChoice 源码，在仓库根目录重新执行安装命令：

   ~~~bash
   git pull --ff-only
   python plugins/buildchoice/setup.py --workspace /absolute/project --runtime-root . --install
   ~~~

3. 使用自定义数据目录时，继续传入相同的 --data-home；每个已登记项目分别运行安装命令。项目设置会保留，可按需使用 --decision-mode pilot 或 off 调整。
4. 重新连接 MCP，核对目标项目、运行时和开关。安装自检见[故障排查](TROUBLESHOOTING.md)。

项目账本保存在项目自身的目录中。更新插件不需要清空账本，也不需要重建已确认选择。

## 使用运行包

在源码目录运行 python scripts/build_distribution.py，可在 dist 中生成核心运行包、插件包及对应的 SHA256 文件。核对校验和，将插件包解压到独立目录，在其中执行：

~~~bash
python setup.py --workspace /absolute/project --bundle /absolute/buildchoice-core-VERSION.zip --decision-mode pilot --install
~~~

将 VERSION 替换为实际文件中的版本号。更新运行包安装时，先备份项目账本与安装绑定，再用独立的 --data-home 初始化并安装；不要覆盖正在使用的运行目录。项目设置保存在安装数据目录内，使用新目录后需要重新配置。

## 项目与运行模式

同一安装数据目录可以登记多个项目，各自保存绑定与运行设置：

~~~bash
python plugins/buildchoice/setup.py --list-projects
python plugins/buildchoice/setup.py --use-project /absolute/project
python scripts/buildchoice_decisions.py --workspace /absolute/project settings
python scripts/buildchoice_decisions.py --workspace /absolute/project off
~~~

切换后重新连接 MCP。关闭决策卡即可停止卡片流程，不需要删除项目数据。项目匹配、文件位置和独立配置见[项目使用与切换](PROJECTS.md)。
