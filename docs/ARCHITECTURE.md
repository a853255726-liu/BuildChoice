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
         一次提取：候选 + 简短 coverage 依据
                         ↓
         真实来源核验 → 确定性四状态 → 对话单卡
                         ↓
       Hook 观察明确选项回复 → V3 Ledger 与版本历史
```

Hook 不负责语义分类。`coding_request()` 仅提供正向提示，匹配失败不阻止生成句柄。句柄本身不要求发卡或调用工具；普通解释与咨询直接回答。已有待答卡的回复优先关联到原任务。

## 模块边界

Skill 为 Agent 提供工作指引，MCP 暴露有状态工具，Hook 关联宿主观察到的用户消息。指引与工具返回内容不具备额外的操作授权。

- `decision_memory.py`：从真实 Hook 确认派生项目参考；管理动作作为 MEMORY_ACTION_OBSERVED 事件保存，跨聊天检索不扩大原任务访问权限。普通参考 30 天后归档，长期规则需要明确的用户管理请求；记忆不生成新确认或操作许可。
- `settings.py`：Prompt-first / off；`decision_settings.py`：独立 V3 试用设置。
- `prompt_policy.py` / `decision_hook.py`：澄清原则、工作区范围与真实消息回调。
- `candidate_policy.py`：候选去重、证据/风险/依赖规则及排序。
- `decision_service.py`：来源核验、候选编排及覆盖记录。
- `decision_store.py`：SQLite 事务、短期句柄、单卡、版本、确认与历史。
- `decision_cards.py`：固定文本模板。
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

工具实际读取文件，保存内容与 SHA256。JSON pointer 核对结构化字面值；精确文本引用检查原文是否存在，解释仍需复核。文件变化会使旧复核指纹失效。确认来自当前会话有效卡片的明确回复，Agent 转述不升级为可信确认。

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
| 0.10.1 | 产品发布版本，写入插件元数据和分发包名称 |
| V3 / decision.v3 | 决策卡流程及其数据契约，与产品版本分别演进 |
| audit.v1 | 文件来源、引用与兼容审计记录格式 |
| memory.v1 | 项目决策记忆的查询结果格式 |
| candidate-extractor-v3.7 | Agent 候选提取指引版本 |

.claude-plugin/marketplace.json 是当前安装器使用的本地市场兼容布局；plugins/buildchoice/.codex-plugin/plugin.json 是 Codex 插件清单。安装器在独立数据目录生成插件副本和市场文件；源码内的文件用作模板。install_local.py 通过 openai_codex SDK 调用 Codex app-server 的 plugin/install 和 plugin/read；目录名称不代表运行了 Claude 服务。
