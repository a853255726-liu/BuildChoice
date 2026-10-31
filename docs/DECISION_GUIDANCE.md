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

0.8.1 起，已加载新代码的 MCP 连接会在原生设置或 CLI 改变工具可见性时发送列表变更通知，宿主收到后重新获取工具。升级服务代码本身仍需重新连接或重启 Codex。

## 触发与对话

1. V3 开启时，工作区内有效 UserPromptSubmit 提供 `buildchoice-v3-ctx-...` 短期句柄，不以开发正则作为准入门槛。
2. Agent 结合当前消息和上下文判断是否正在实施开发，能处理“给现有项目加登录”“这里改成自动保存”“按刚才说的做”等短句。纯解释与咨询直接回答，句柄本身不要求筛选或提问。
3. 实际开发时一次提取候选与覆盖依据；不增加第二轮复核。INSPECT 先查资料；DEFER 留到依赖步骤；ASK_NOW 一次一张卡；零候选直接继续。
4. 用户明确回复 A/B 或卡号加“选 A”，只绑定同会话、未过期、当前版本的一张待答卡。解释、自由回答和混合指令不自动确认。
5. 用户改变选择时追加版本，再明确确认；保留旧记录，受影响实现标记待复核。

新任务 task_text 保持本轮用户原文，不能把对话重写为伪造的用户消息。仅重筛同一任务时使用原 task_id 与 task_text；本轮扩展任务目标时用本轮原文建立新范围。前文帮助理解，但不替代真实消息绑定。

0.8.3 的消息匹配仅统一传输换行符和首尾空行；不要改写正文空格、缩进或业务内容。修订与初次筛选都要求选项 ID 唯一，推荐项必须存在。

筛选重试若收到 CACHED_SCREEN_STALE，说明来源、未读资源、决定/确认或覆盖状态已变，或旧缓存没有可验证快照。先读取当前资料与任务状态，再以新幂等键筛选，不继续使用旧 PROCEED 或旧卡面。筛选中断会整体回滚，相同请求可安全重试；相同键改变语义输入仍会被拒绝。

有待答卡时，解释请求仍可沿原 task_id 继续；用户切换到另一任务时，Agent 使用当前句柄、本轮原文且不传旧 task_id 建立新范围，服务端解除旧卡的待答占用。旧决定与历史保留，未因此被确认；恢复旧任务时应重新激活并展示卡片。过期卡同样解除占用，过期后到达的 A/B 回复不会确认旧决定。当前有效卡仍保持同会话一次一张。

0.8.2 起，激活重试只在同一卡面和版本仍为当前有效待答卡时返回缓存，不延长有效期。已确认、过期、修订或被其他卡替代的旧请求会报错；先查询状态，恢复时使用新的幂等键，不展示旧缓存文本。

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

## 关联实际实现

在原有实现过程中顺带调用 buildchoice_link_implementation，提交 task_id、decision_id、当前 revision、实际相对路径和简短 note，可附真实起止行号与当前句柄。不另起一轮审查，不将计划中的文件或不存在的行号登记为已实现。

查询 buildchoice_decision_status 可查看 implementations。修改选择后，旧版本的关联进入待复核；代码文件变化或不可读也会提示复核。新版本修改完成后重新登记到当前版本，旧历史保留。该动作不会把 Agent 自报升级为用户确认或正确性证明。

## 迁移与回退

0.8 可在相关实现完成时按需使用验收条件与行为验证，条件由 Agent 从当前已确认选择推导，测试必须通过现有授权路径显式执行。无测试只能标为未验证；文件关联不能替代行为证据。见 [决策落实验证](DECISION_VERIFICATION.md)。

```bash
python scripts/buildchoice_decisions.py --workspace /path/to/project migrate
```

首次建立 V3 表前备份 SQLite，audit.v1 含义不变。关闭 V3 即可停用。若确需移除 V3 表，关闭试用并停止相关会话后显式运行 rollback；回退先完整备份当前数据库，再只移除 V3 表，保留 audit.v1。

## 信任与保存

句柄依赖受信任本地宿主回调，不是防御能任意修改本用户数据库或执行本地回调的程序的密码学边界。默认保存摘要、消息哈希、选项、覆盖理由和状态，不无差别保存聊天全文，不自动上传。原生工具权限和审批独立。
