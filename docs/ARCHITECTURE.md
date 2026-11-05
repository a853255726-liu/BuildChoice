# BuildChoice · 架构

本文面向贡献者，介绍 Codex 插件的运行流程与模块边界。BuildChoice 由 Skill、MCP、UserPromptSubmit / PostToolUse Hook 和本地 SQLite 账本组成，提供决策引导、项目记忆、资料读取记录与可选代码关联。

## 主流程

```text
UserPromptSubmit → 工作区检查 → Prompt 澄清原则
                         ↓ V3 开启
                  短期会话/轮次句柄
                         ↓
        主 Agent 根据当前消息与上下文判断是否实施开发
                         ↓
         一次取得任务状态、项目记忆与有效资料
                         ↓
         LLM 提取候选 + 处理建议 + coverage
                         ↓
         程序核对格式、来源与版本 → 对话单卡
                         ↓
       真实消息直接解析 / LLM 解释 → 记录来源与版本
                         ↓
           断点恢复、项目复用、文档与变化摘要
```

Hook 不负责语义分类。`coding_request()` 仅提供正向提示，匹配失败不阻止生成句柄。句柄本身不要求发卡或调用工具；普通解释与咨询直接回答。已有待答卡的回复优先关联到原任务。

## 模块边界

Skill 为 Agent 提供工作指引，MCP 暴露有状态工具，Hook 关联宿主观察到的用户消息。指引与工具返回内容不具备额外的操作授权。

- `decision_memory.py`：从真实 Hook 确认派生项目参考；管理动作作为 MEMORY_ACTION_OBSERVED 事件保存，跨聊天检索不扩大原任务访问权限。普通参考 30 天后归档，长期规则需要明确的用户管理请求；记忆不生成新确认或操作许可。
- `settings.py`：Prompt-first / off；`decision_settings.py`：独立 V3 试用设置。
- `prompt_policy.py` / `decision_hook.py`：澄清原则、工作区范围与真实消息回调。
- `candidate_policy.py`：结构化去重、引用核验结果与 LLM 声明的处理建议、优先级；不进行风险语义分类。
- `decision_service.py`：来源核验、候选编排及覆盖记录。
- `decision_store.py`：SQLite 事务、短期句柄、单卡、版本、确认与历史。
- `decision_cards.py`：固定文本模板。
- `task_context.py`：同聊天上下文打包、有效读取复用、预算与字面变化快照；最多保留 100 份摘要快照。
- `reply_interpretation.py`：将 LLM 对自然回复的解释绑定到实际消息与冻结卡片，单独记录 provenance。
- `decision_document.py`：账本的可读 Markdown 投影与字面修订差异，保护手写文档。
- `implementation.py`：真实文件位置与哈希、Agent 登记的实现关联及变化提示。
- `acceptance.py`：当前确认绑定、不可变验收条件及独立版本。
- `verification_inputs.py` / `verification.py`：声明输入/环境指纹、执行回执核对、逐项结论和动态失效；MCP 不执行项目命令。
- `verification_runner.py` / `verification_worker.py`：仅显式 CLI 启动的固定 unittest 采集器，保留真实用例、退出码、输入前后快照和报告哈希。
- `doctor.py`：只读本地安装与可选宿主声明检查，未知状态不报为通过。
- audit.py：共享账本、受限文件读取、引用定位与兼容审计记录，为决策、记忆和验证提供证据基础。
- `buildchoice_mcp.py`：按需审计、决策卡、项目记忆与原生设置。

## 覆盖依据

`coverage` 与候选在同一次提取中形成，不安排第二轮 Agent 复核。只记录当前相关维度，最多六项，每项理由最多 300 字符。状态为 resolved / candidate / not_applicable / uncertain。

服务端核对来源是否真实读取、引用是否存在以及文件是否变化，并保存 `COVERAGE_RECORDED` 事件；最新一轮记录可由任务状态读取。Agent 声明保留为 `agent_declared`，`does_not_establish_completeness=true`。即使零候选也可保存依据。未提交 coverage 时显示 reported=false。

覆盖元数据不进入候选分流，不会单独发卡、阻塞执行或授予操作权限。文件引用有效也不证明 Agent 对“已有答案”或“不适用”的解释正确。

## 账本与证据

audit.v1 包含 sessions、sources、decisions、reviews、events；V3 使用独立的任务、候选、确认、上下文、激活卡、幂等操作和事件表。覆盖依据作为事件保存。

显式读取器保存文件内容与 SHA256，观察读取只保存范围及哈希。JSON pointer 核对结构化字面值；精确引用检查原文是否存在，语义和适用性由 LLM 判断。文件变化使旧来源和缓存失效，不撤销用户原选择。

可直接解析的真实卡片回复记录 user_message_observed。复杂回复由 LLM 提交实际本轮原话与解释，程序核对当前消息、卡片、选项、版本和有效期，记录 llm_interpreted_user_reply、semantic_verified_by_program=false。无真实消息的 Agent 自述不能创建确认。仅待解释的当前回复在内部保存必要原文，不保存完整聊天。

明确的新指令使用独立的 instruction.v1 请求，不要求激活卡片。程序以 Hook 的本轮消息哈希核对完整原话，再检查精确引用、任务归属、预期版本和幂等键；保存 llm_interpreted_user_instruction 与引用片段，语义和范围解释由 LLM 负责。已确认相同选择仅追加来源事件；变化追加版本，未激活的提案也可由真实指令选择，不补造卡片交付。

指令事务同时保存文档投影待办。提交后在写锁下重新生成当前已确认项目记录，以临时文件加原子替换发布；失败保留 pending，重试不会再次生成决定版本。SQLite 是状态依据，文件同步状态单独返回。context 可发现文件缺失、修改或后续账本变化；同名手写文件不会被覆盖。附加表按需创建，旧 SQLite 与原确认表保持兼容。

上下文查询聚合任务、记忆、来源和恢复建议，部分/过期读取不提升为完整有效来源。快照按工作区和宿主聊天隔离，保存哈希与状态，不复制文件正文；快照字面变化不判定业务影响。重复激活当前卡不续期、重复回复解释不新增确认，暂缓项不自动重新询问。

## 实现关联

代码关联为可选功能，不要求每次开发登记。只有当前真实 Hook 已确认的决定可关联文件、可选行号和简短关系说明，事件同时保留 confirmation_id。服务端只读文件并保存 SHA256，复用 IMPLEMENTATION_LINKED 事件；不分析 Diff 或代码语义，不运行 Git 子进程。

状态查询重新核对文件；决定版本变化或文件变化时标记对应关联待复核。provenance 始终为 agent_reported_implementation，不能从“哈希未变”推断实现正确。旧确认、审计和事件不受影响，不增加数据库表。

## 安装与范围

正常测试、验收与结果解释使用 Codex 原生能力。专用验收与验证接口为按需实验，只有用户明确要求时使用。

Python 包、插件 ID、MCP 服务键统一为 buildchoice。安装数据使用 ~/.buildchoice，项目账本使用 .buildchoice_audit。插件注册 UserPromptSubmit 和 PostToolUse；后者用 read_observer.py 观察窄范围真实读取，复用 audit.py 来源/事件，仅保存路径、返回范围、版本哈希和调用信息，正文不落库。服务端重建当前范围、检查引用并使相关缓存失效；不证明 LLM 理解资料或用户同意。宿主审批与 Hook 信任保持独立。详见[读取观察](PROJECT_READS.md)。

模式 off 停用提示、证据写入、决策卡、项目记忆及验证；设置和关闭状态仍可查询。升级方式见 [升级说明](UPGRADING.md)。

## 名称与兼容目录

| 标识 | 用途 |
|---|---|
| 0.12.0 | 产品发布版本，写入插件元数据和分发包名称 |
| V3 / decision.v3 | 决策卡流程及其数据契约，与产品版本分别演进 |
| audit.v1 | 文件来源、引用与兼容审计记录格式 |
| memory.v1 | 项目决策记忆的查询结果格式 |
| context.v1 / decision-document.v1 | 上下文与可读决策文档结果格式 |
| candidate-extractor-v4.0 | Agent 候选提取指引版本 |

.claude-plugin/marketplace.json 是当前安装器使用的本地市场兼容布局；plugins/buildchoice/.codex-plugin/plugin.json 是 Codex 插件清单。安装器在独立数据目录生成插件副本和市场文件；源码内的文件用作模板。install_local.py 通过 openai_codex SDK 调用 Codex app-server 的 plugin/install 和 plugin/read；目录名称不代表运行了 Claude 服务。
