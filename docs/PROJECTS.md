# BuildChoice · 项目绑定与切换

## 添加项目

每个项目保存独立绑定、运行设置与账本。同一个安装数据目录可登记多个项目：

~~~bash
python plugins/buildchoice/setup.py --workspace /absolute/project-a --runtime-root . --decision-mode pilot --install
python plugins/buildchoice/setup.py --workspace /absolute/project-b --runtime-root . --decision-mode pilot --install
~~~

安装器将插件清单、MCP 与 Hook 配置写入独立的 installations 目录，不重写源码中的配置。Python 环境默认在安装数据目录复用；项目的 Prompt-first 和决策卡开关分别保存。

## 查看与切换

~~~bash
python plugins/buildchoice/setup.py --list-projects
python plugins/buildchoice/setup.py --use-project /absolute/project-a
~~~

MCP 新连接会优先匹配启动目录所属的已登记项目；嵌套项目选择最具体的绑定。启动目录没有对应项目时，使用显式选中的活动项目。Hook 按消息中的项目目录选择绑定，未登记目录不产生项目记录。

切换活动项目后重新连接 MCP 或重启 Codex。已有连接保留原绑定，不会把正在进行的任务静默移到另一项目。每次安装采用同一市场名称，插件入口负责分派项目，无需为每个项目创建一组工具。

## 项目设置

可在添加或切换时传 --decision-mode pilot / off，也可指定项目修改设置：

~~~bash
python scripts/buildchoice_decisions.py --workspace /absolute/project-a pilot
python scripts/buildchoice_settings.py --workspace /absolute/project-a off
~~~

使用自定义安装目录时，为以上命令追加 --data-home /absolute/buildchoice-data。也可显式传 --config 直接操作一份配置文件。

## 文件位置

默认安装数据目录为 ~/.buildchoice，可用 --data-home 或 BUILDCHOICE_DATA 指定其他位置：

- projects.json：已登记项目与活动项目。
- projects/<project_id>/binding.json：项目绑定。
- projects/<project_id>/configs/：项目运行设置。
- installations/<package_id>/buildchoice/：生成的独立插件副本。
- binding.json：兼容旧工具的活动绑定。

项目 ID 按规范化后的绝对路径计算。移动项目后重新登记新路径。账本仍保存在项目自身的 .buildchoice_audit/ledger.sqlite3，不跨项目共享。

旧版单项目 binding.json 可以继续读取。重新初始化后会加入项目注册表；若尚无独立插件副本，先按当前安装方式重新初始化，再执行 --install。
