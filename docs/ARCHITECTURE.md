# BuildChoice · 架构

## V3 独立试验层

主 Agent / Skill 提取候选 → decision.v3 契约 → 实际来源核验 → 可用的 NLI 第二意见 → 确定性四状态 → 对话单卡 → 真实 Hook 回复关联 → 独立 V3 Ledger 表。

`candidate_policy.py` 处理规则与排序；`nli_candidate_adapter.py` 保持原字段模型限制并记录降级；`decision_cards.py` 提供固定模板；`decision_store.py` 使用 SQLite 事务、轮次句柄、单卡状态及版本；`decision_service.py` 编排这些模块。开关在独立 `decision_v3.json`，默认关闭。

NLI 不判断产品决策权或用户授权。旧模式与 audit.v1 路径保留在下方。

```text
用户任务 → Prompt 澄清原则 → 主 Agent → 查资料 / 提问 / 执行
                            │
                       按需登记审计
                            ↓
                本地 Web / CLI / MCP
                            ↓
                    Ledger + SQLite
                            ↓
         字面取值核对 / 引用定位 / 来源新鲜度
                            ↓
                    复核记录与报告

可选：MCP → 本地 HTTP → GateEngine → PredictorBackend → NLI
```

## 模块边界

- `prompt_policy.py`：版本化澄清原则及工作区范围内的消息附加。
- `auto_call.py` / `native_settings.py`：持久化运行模式，默认关闭分类器推断入口。
- `audit.py`：来源快照、决定、引用、发现、复核及报告；所有入口复用同一核心。
- `audit_web.py` / `audit_web/`：本机单用户工作台，标准库 HTTP 与静态前端。
- `codex_gate_mcp.py`：Agent 的按需审计入口及可选分类器桥接。
- `engine.py` / `contracts.py`：版本化请求、revision、证据哈希和响应形状。
- `required_call.py`：可选强制模式中，将真实调用回执绑定到当前会话和轮次。
- `backends/` / `predictor/`：可选模型接口与字段级推断。

## 账本数据

| 表 | 内容 |
|---|---|
| sessions | 任务声明、工作区、标题、时间、来源类型 |
| sources | 工具实际读取的文件内容、相对路径、SHA256、读取时间 |
| decisions | 决定、取值、影响、理由、具体引用 |
| reviews | 当前状态下的处理意见、说明和状态指纹 |
| events | 创建、读取、登记和复核的事件轨迹 |

每次决定登记追加一条记录，不覆盖原始决定。调用方不能通过传入“已读取”字段替代实际文件读取。

## 核验与状态

JSON pointer 对结构化值进行类型严格的字面比较。多个所引值不同会产生冲突提示；文档之间的版本替代和适用范围由复核者判断。

精确文本引用检查原文是否存在；存在时仍标记解释待复核。没有引用、路径失效、取值不一致和来源变化分别记录。

复核意见绑定决定、当前引用状态和问题集合的指纹。文件变化后，旧意见不再作用于新状态，但原记录保留。

## 执行与持久化

默认任务路径仅注入原则，不自动提交模型或审计请求。审计由使用者或 Agent 显式发起。

工作台与 MCP 使用目标工作区的 `.gate_audit`。分类器 worker 的 token 和调用状态另存于运行时 `runs/desktop_gate`。配置和资源绑定由插件初始化器管理，插件不自动修改宿主 Hook 信任。
