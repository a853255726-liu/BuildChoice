# BuildChoice · 决策卡使用说明

V3 默认关闭。主 Agent 在实际开发时发现候选，服务端依据项目证据和规则分流；用户在原对话逐张回答。项目已移除小判别模型，不需要下载权重或启动推理服务。

## 开关

```bash
python scripts/buildchoice_settings.py status
python scripts/buildchoice_decisions.py settings
python scripts/buildchoice_decisions.py pilot
python scripts/buildchoice_decisions.py off
```

原生设置提供 Prompt 优先 / 完全关闭和独立 V3 试用开关。完全关闭停用提示、MCP 审计与决策卡；重新启用 Prompt 优先后，仍使用保存的 V3 选择。

## 触发与对话

1. V3 开启时，工作区内有效 UserPromptSubmit 提供 `buildchoice-v3-ctx-...` 短期句柄，不以开发正则作为准入门槛。
2. Agent 结合当前消息和上下文判断是否正在实施开发，能处理“给现有项目加登录”“这里改成自动保存”“按刚才说的做”等短句。纯解释与咨询直接回答，句柄本身不要求筛选或提问。
3. 实际开发时一次提取候选与覆盖依据；不增加第二轮复核。INSPECT 先查资料；DEFER 留到依赖步骤；ASK_NOW 一次一张卡；零候选直接继续。
4. 用户明确回复 A/B 或卡号加“选 A”，只绑定同会话、未过期、当前版本的一张待答卡。解释、自由回答和混合指令不自动确认。
5. 用户改变选择时追加版本，再明确确认；保留旧记录，受影响实现标记待复核。

新任务 task_text 保持本轮用户原文，不能把对话重写为伪造的用户消息。仅重筛同一任务时使用原 task_id 与 task_text；本轮扩展任务目标时用本轮原文建立新范围。前文帮助理解，但不替代真实消息绑定。

激活卡片不证明 UI 已展示。缺少受信任 Hook 时可正常聊天，但确认保持 `agent_reported_unverified`。

## 覆盖依据

在原有提取中顺带记录，最多六项：数据与保存、权限与可见性、自动化与确认、外部依赖与费用、失败与恢复、范围与交付。只填相关维度，不机械填满。

```json
{
  "candidates": [],
  "coverage": [
    {"dimension":"access_visibility","status":"resolved","reason":"项目约束明确仅本人可见","evidence_refs":[{"source_id":"src-...","quote":"仅本人可见"}]},
    {"dimension":"external_cost","status":"not_applicable","reason":"本次只修改本地展示逻辑"},
    {"dimension":"failure_recovery","status":"uncertain","reason":"当前尚未查清失败后的恢复要求"}
  ]
}
```

这是筛选请求的局部示例，完整请求还需 task_text、phase、next_step、idempotency_key 和当前句柄。status 可为 resolved / candidate / not_applicable / uncertain；候选关联使用 request 内真实 candidate_id。

服务端核对 source_id、引用与当前文件哈希，返回独立 source_status；未核实内容不会变成真实来源。coverage 仍是 Agent 声明，不证明没有遗漏，不单独触发卡片或改变四状态。记录存入已有 V3 事件，`buildchoice_decision_status` 可读取最新结果。

## 迁移与回退

```bash
python scripts/buildchoice_decisions.py --workspace /path/to/project migrate
```

首次建立 V3 表前备份 SQLite，audit.v1 含义不变。关闭 V3 即可停用。若确需移除 V3 表，关闭试用并停止相关会话后显式运行 rollback；回退先完整备份当前数据库，再只移除 V3 表，保留 audit.v1。

## 信任与保存

句柄依赖受信任本地宿主回调，不是防御能任意修改本用户数据库或执行本地回调的程序的密码学边界。默认保存摘要、消息哈希、选项、覆盖理由和状态，不无差别保存聊天全文，不自动上传。原生工具权限和审批独立。
