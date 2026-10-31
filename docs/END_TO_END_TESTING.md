# BuildChoice 0.9 · 端到端测试与效果评估

此文档给出工程集成、实际 Codex 对话和产品 A/B 测试的**可复现步骤**。当前工程证据见 [VALIDATION](VALIDATION.md)。

## A. 自动化工程集成

运行 `.github/workflows/integration.yml`，或在已安装依赖的环境中执行：

```bash
python -m unittest discover -s checks -v
python checks/smoke_mcp.py
python checks/check_package.py
python scripts/build_distribution.py
python checks/run_receipt_demo.py --out receipt-results.json
```

浏览器测试需安装 `requirements-dev.txt`、配置 Playwright Chromium，并指定 `BUILDCHOICE_TEST_BROWSER`。CI Linux 合成浏览器用例使用专用无沙箱启动设置，不改变本地默认行为。

成功标准：单元与协议回归通过；MCP 真正启动并接受调用；运行包能初始化；同一组真实浏览器测试在正确实现上通过，并在两种故意错误实现上触发预期失败。模拟 Hook 事件与浏览器行为属于工程集成证据。

## B. 实际 Codex 对话验收

在可登录 Codex 的环境中，用独立测试工作区安装当前插件。每项检查保存对应会话的日志和当前 Git 提交：

1. 执行 `python scripts/buildchoice_doctor.py --host --json`，核对插件、MCP 工具、Hook 声明和工作区绑定。
2. 执行 `python scripts/buildchoice_decisions.py pilot`，在新的 Codex 会话输入一个不指定保存方案的开发任务，例如「开发能识别购物小票金额和类别的记账功能」。
3. 记录 Agent 是否依据实际项目约束提取有意义的候选；若判断存在关键选择，应先查证据，再展示单张卡。没有发现也必须记录，不能删掉失败样本。
4. 用户真实提交卡面提供的一个选项；查询 `buildchoice_decision_status`，核对当前 decision、revision 与来自宿主 Hook 的 `user_message_observed`。不要用本地模拟事件替代真实回答。
5. 继续完成实现并在允许的命令执行范围内运行行为测试；调用 `buildchoice_acceptance_prepare`、显式采集器及 `buildchoice_verify_decision`，记录验收项、真实退出码和当前适用性。
6. 更改与已确认决定有关的代码，再查询实现关联与验证结果；历史记录应提示需要复核。恢复代码及重新运行验证后记录新结果。
7. 再测试三类负例：已经明确方案的需求、低影响视觉调整、纯咨询。检查是否出现不必要的阻塞提问。
8. 在同一项目中新建会话，查询决策记忆；测试普通参考、标记长期、遗忘与恢复，核对相关选项是否仅在适用范围内被复用，不将历史记忆当作当前敏感操作许可。

推荐保存：Codex 版本和模型、BuildChoice 提交 SHA、完整原始指令、项目资料快照、用户回复、卡片内容、用例、执行回执、工具调用次数和总耗时。公开报告需去除敏感个人数据与本机路径。

## C. 产品效果对照实验

将真实开发指令及必要的项目状态恢复为固定输入；在运行前由独立评审标注需要当前确认的关键决策，保留确定不需提问的负例。

建议比较以下两组：`Codex + Prompt-first` 与 `相同 Codex + BuildChoice`。保持基础模型、初始资料、权限和时间预算一致，重复运行并随机化顺序。

- **关键决策有效发现率**：及时发现的 Gold 决策 / 全部 Gold 决策机会；同义重复问题只计一次。
- **无效阻塞追问率**：在无需确认任务中，至少一次多余阻塞追问的运行占比。
- **交互成本**：任务耗时、额外用户轮次、工具/模型调用。
- **实现验证专项**：对两组提供同样已确定的用户选择和独立行为测试，统计最终一致率；在受控正确/错误实现上分别计算检出率和误报率。

对真实任务的统计以原始任务为单位进行配对或分层分析；重复运行不作为新的独立任务。保留超时、失败和无法恢复上下文的记录，明确 Gold 决策来源和评审分歧处理。

有关所有指标的证据层级和适用范围，参见 [VALIDATION](VALIDATION.md)。
