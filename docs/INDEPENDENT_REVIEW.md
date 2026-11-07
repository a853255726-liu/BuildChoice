# 独立上下文审阅（0.15.1）

目标是减少执行者持续解释自身实现造成的盲区，同时避免审阅者因缺少约束而误判。插件管理来源与版本，宿主管理独立上下文，模型判断产品适配性；不加入模型依赖、API Key 或常驻模型服务。

审阅核心是判断交付物在已知约束下是否支持用户目标；区分实质偏差、合理实现选择和信息不足。用户意图包括明确要求与达成目标必需的基本条件，普通未指定细节允许自主实现；缺少逐项认可本身不是偏差。约束不能扩大到其适用对象之外。

默认只做一次整体审阅，按影响选择检查范围。有具体重要疑点才查额外证据、补背景或复核；先自行取证，业务取舍再问用户。不强制穷举类别、完整矩阵、多轮或多角色。issues 保留有依据的潜在偏差，questions 保留影响结论的信息缺口，允许均为空；处理完重要疑点或明确待查范围即可结束。普通低影响任务沿用直接检查。

0.15.1 收敛审阅指令与 Skill，不新增字段、工具、语义分类器或发布门槛，0.15.0 的请求和记录保持兼容。三类判断由模型完成，程序继续只核对引用、状态和版本。可通过快照清单定位缺失资料；超出当前交付物证据范围时准备新包，不降低引用校验。

```text
原任务 / 明确纠正 / 已确认决定 / 分域约束 + 当前交付物快照
                 ↓ prepare_independent
宿主 spawn_agent(fork_turns=none, 继承模型) → submit_independent 首轮判断
                 ↓ 有具体疑问时
provide_background → 同一审阅者 followup_task → reconsider_independent
                 ↓
逐项采纳或说明排除原因 → create / supplement → 实际用户反馈
```

入口沿用 experience 和 behavior_review，日常/完整工具数量保持 14/24。experience enable 的 review_policy=independent 按任务开启发布门槛；省略保持原值，普通任务默认 standard。旧记录和已有流程保持可读。

prepare_independent 校验原始 task 输入摘要、当前用户 Hook 引用、可信决定版本、实际读取的项目引用；项目当前说明只能作约束/背景，不能充当原始用户认可。首轮排除执行者解释。事实的 scope/解释属于模型声明，不代表程序理解了要求。

材料仅从选定快照的安全文本及指定行范围还原；附文件清单、范围与字符预算，不静默截断。凭据、二进制、大文件和未捕获文件沿用快照排除规则。包中包含 response_contract，发现必须引用已披露的实际行与原文。相关文件/需求是否齐全仍需模型判断，不能声称完整覆盖。

首轮、每次问题定向补充、复核的 keep/revise/withdraw/add 原因都追加保存。expected_revision 防止覆盖；项目来源或快照变化会使旧审阅失效。最终反馈必须处理每个当前发现；排除需要理由，采纳需要真实 finding 映射。补充背景后阻止尚未复核的发布。零发现且无疑问无需第二轮。

独立上下文由宿主执行并声明；agent_id/fork_turns 元数据不构成程序可认证的隔离证据。子 Agent 继承权限并共享文件系统，角色的只读指令不是安全沙箱。插件不授权任何宿主操作。宿主不支持独立上下文时不得伪造结果或自行降级后称独立审阅完成。

详细宿主操作见[Skill 参考](../plugins/buildchoice/skills/decision-discovery/references/independent-review.md)。自动测试包含明确标注的合成 Hook，不等于真实 UI/用户确认。真实宿主演练单独记录首轮输出和后续复核，也不能证明对所有产品问题都有效。

## 可选专题与冻结指导

prepare_independent 新增可选 `review_topics` 数组，允许 interface、documentation、debugging 的唯一项，最多三个；省略或 [] 保持核心审阅。由编排者按任务与实际交付选择，不按词语或已知缺陷自动触发，不让用户决定内部加载。inputSchema 与实际执行共用 product_contracts。

新材料包保存指导的实际文字、规则／专题 ID、版本、摘要和复核动作。materialize 不重新从现行目录生成旧输入；provide_background 继承同一包的指导身份与复核动作。无 guidance 的历史包使用源码保留的 0.15.2 原文并标 legacy-0.15.2，需要新原则时重新 prepare。正文与元数据均计入 max_chars，失败不发布半成品。

payload.guidance 披露指导身份；target_identity 披露实际 workspace/task_id/snapshot_id。原文件与哈希仍在 artifacts／inspection_inventory 中。对象的语义定位由主 Agent 负责，包内关联不等于选择正确。新聊天不证明没有 AGENTS 等宿主输入，也不构成只读沙箱；实际验证需记录环境。引用错位返回 EVIDENCE_REPAIR_REQUIRED 的字段／安全路径／行范围，不回显原文或错误 quote。
