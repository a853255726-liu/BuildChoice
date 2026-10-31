# BuildChoice · 决策落实验证（0.8）

用户选定产品行为后，BuildChoice 可保存验收条件，再核对已执行测试是否支持该选择。原有候选、分流、卡片、Hook 确认与决策版本流程不变，验证按需接入正常开发测试，没有每次调用后的自动检查。

## 最小闭环

1. 开启 V3，按原有流程完成当前决策版本的 Hook 确认。自由回答、Agent 复述、过期句柄、跨会话任务均不能替代确认。
2. 调用 `buildchoice_acceptance_prepare`，提交从该选择推导的具体条件及对应 unittest 用例 ID。返回的集合不可变，关联实际 choice、confirmation_id、decision_id 和 revision。`criterion_author=agent`，`human_approval=not_separately_confirmed`；新增产品规则应重新确认。
3. 编写有实际行为断言的测试和输入清单。在已有命令权限范围内显式执行采集 CLI。MCP 不执行项目命令，用户要求只审查时不能顺带运行。
4. 调用 `buildchoice_verify_decision` 传采集返回的 execution_id，可附通过 `buildchoice_audit_read` 读取的代码引用。结果保存到 V3 事件；用 `buildchoice_decision_status` 查询当前有效性。

## 显式采集

清单为工作区内 JSON 文件，路径相对工作区；固定 Python unittest 适配器，不能传 shell 或任意命令：

```json
{
  "adapter": "python-unittest-v1",
  "test_file": "tests/test_receipt.py",
  "files": {
    "implementation": ["index.html", "app.js"],
    "tests": ["tests/test_receipt.py"],
    "fixtures": ["receipt.json"],
    "config": ["config.json"]
  },
  "dependencies": ["playwright", "pyee", "greenlet"],
  "timeout_seconds": 60,
  "scope": "合成识别结果进入核对页后，到本地正式账本保存的流程"
}
```

```bash
python /absolute/BuildChoice/scripts/buildchoice_run_verification.py \
  --workspace /absolute/project --acceptance-id acc-... --manifest manifest.json
```

使用与 MCP 相同运行时的 Python、全局和 V3 设置，以及所声明的依赖环境；浏览器变量也应保持一致，否则结果可能显示环境已变化。独立配置可显式传 `--settings` 和 `--decision-settings`。采集器要求已有确认及验收，不自动初始化任务或确认。执行完成会返回 execution_id、实际退出码和测试数，采集成功本身不是验收通过。用例 ID 为 `buildchoice_tests.类名.方法名`。

采集器记录启动/完成时间、固定 argv、工作区、随机执行关联值、真实退出码、用例结果、报告/日志哈希、运行前后声明文件快照、运行时和环境指纹。每次隔离字节码缓存，避免短时间同大小源码修改后执行旧缓存。超时（最多 120 秒）、输出超过 1 MiB、启动错误或缺少内部报告不能成为通过；标准输出中的“passed”无效。MCP 只接受匹配启动事件的采集记录，不接受报告路径或 Agent 自报通过。

环境指纹包含实际解释器、显式声明 Python 发行包文件，以及 `BUILDCHOICE_TEST_BROWSER` 选定的浏览器与可定位的 Chrome/Edge 引擎文件。项目须主动声明相关配置、测试辅助文件和依赖；没有覆盖所有系统库、所有环境变量、网络服务、未声明文件或整个仓库。测试在当前用户权限下运行，不是恶意代码沙箱；有权限改写账本/运行时的本地程序不在防伪边界内。不要运行不可信测试。

## 解释结果

| 字段 | 含义 |
|---|---|
| `passed` | 当前评估时，必需条件的已映射行为用例均实际通过 |
| `failed` | 观察到对应行为断言失败 |
| `inconclusive` | 缺少执行、映射、实际测试，或只存在静态证据 |
| `error` | 测试启动/运行错误、超时、输出限制或无法接受的执行状态 |
| `applicability=current/stale` | 该历史结果是否仍适用于当前声明范围 |
| `current_pass` | 历史结论通过，且现在没有失效原因 |

静态引用记录真实来源、路径、哈希和定位情况，不推断代码语义已正确。`coverage_complete=false` 始终保留，条件和测试均由 Agent 编写，实际执行不等于独立验证了断言的充分性。

改变决定版本、替换验收集合、修改声明的实现/测试/fixture/配置/清单、改变指纹内环境或验证规则/运行时、移走或篡改证据，会使旧结果 stale。测试执行中输入变化也不能表示当前通过。历史 verdict 保留；重跑后用新幂等键产生新结果。查询幂等旧结果也重算有效性；旧 passed 不会被直接复用为当前通过。内容恢复为相同快照后可再次适用，标识的是内容版本而非 Git 提交号。

## 拍照记账示例

见 [示例](../examples/receipt_review/README.md)。条件覆盖显示识别结果、允许修改并保存修改值、确认前不写入正式账本、取消不入账。使用合成识别结果、独立浏览器上下文及 localStorage 的实际读写，包含提前保存和忽略修改两种反例。

示例未调用摄像头、OCR、数据库后端或真实小程序平台。测试辅助确认由模拟 Hook 事件产生，不证明目标 Codex 安装已经受信任地捕获用户回答；应另用 doctor 和真实会话检查。0.9 提供独立的[跨聊天决策记忆](DECISION_MEMORY.md)，不跨会话迁移验收确认。自动影响分析、任意测试框架和自动生产验收仍不在本版范围内。
