# BuildChoice · 0.7.0 验证

安装根目录 requirements.txt 后执行：

```bash
python -m unittest discover -s checks -v
python checks/smoke_mcp.py
python scripts/build_distribution.py
```

行为检查覆盖短句与承接请求的 Hook 句柄、关闭和工作区边界、零候选覆盖记录、来源绑定与文件变化、虚构来源、元数据不影响分流、幂等操作、明确选项确认与修订，以及旧设置和账本历史的读取。

MCP 检查启动真实 STDIO 服务，验证初始化、保留的 12 个工具、原生设置、证据审计、真实子进程 Hook 回调、卡片确认与覆盖记录、完全关闭和 V3 关闭后的工具列表，以及真实文件关联、文件变化和决定修订后的待复核提示。

安装自检测试包括缺失绑定、缺失依赖、工作区不匹配和宿主状态未知。实际宿主插件/Hook 信任检查仍需在目标安装中通过 --host 执行，模拟返回不视为真实宿主验收。检查只写独立临时工作区，不修改用户插件安装或宿主 Hook 信任；临时记录保留以便检查，可用 BUILDCHOICE_CHECK_ROOT 指定父目录。

上述检查验证本地实现与协议，未进行实际 Codex 插件安装或真实用户任务评测。它们不证明漏问率、误问率或打断次数已经下降。coverage 是 Agent 声明；即使来源引用有效也不代表没有遗漏。
