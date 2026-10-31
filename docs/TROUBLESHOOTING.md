# BuildChoice · 故障排查

BuildChoice 安装后在 Codex 对话中工作。请在安装源码或已绑定的运行时目录执行下面的命令。

## 安装自检

~~~bash
python scripts/buildchoice_doctor.py
python scripts/buildchoice_doctor.py --host --json
~~~

默认检查本地绑定、目标项目、Python 依赖、运行时入口和独立 MCP 启动。--host 额外读取 Codex 插件与 Hook 声明。结果中“未验证”表示尚未取得所需证据，自检不会自动安装、改配置或信任 Hook。

| 现象 | 处理方式 |
|---|---|
| 没有安装绑定或路径失效 | 按 README 使用已有项目路径重新运行 setup.py，确认运行时和 Python 仍存在 |
| 插件未安装或未启用 | 完成 setup.py --install，并在 Codex 中确认插件启用 |
| Hook 未启用或信任未知 | 在 Codex 按正常流程审阅当前 Hook；不要从测试回调推断真实会话已就绪 |
| 决策卡不开启 | 查看决策卡设置，执行 buildchoice_decisions.py pilot；同时检查全局模式不是 off |
| 工具列表没有刷新 | 更新后重连 MCP 或重启 Codex；工具列表变更通知依赖宿主支持 |
| 安装绑定到另一项目 | 使用该项目的绑定，或以独立 --data-home 初始化另一个项目 |
| 修改代码后旧结果失效 | 重新运行相关行为测试，再要求 Codex 验证当前选择 |

安装路径和参数见[README](../README.md#安装)。独立数据目录可通过 doctor 的 --data-home 指定；不要将其他项目的账本覆盖到当前项目。

## 对话正常但没有决策卡

资料已有答案、修改影响较小或请求只是咨询时，可以正常继续而不显示卡片。若重要选择确实遗漏，可直接告诉 Codex 哪项行为需要确认；记录原需求与遗漏情况，便于复现问题。

本地 MCP 启动成功只能证明该服务可连接。要验证真实对话中的插件加载和回复绑定，参见[端到端测试](END_TO_END_TESTING.md)。
