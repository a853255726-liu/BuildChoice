# BuildChoice · 架构

BuildChoice 保留 Prompt-first、按需证据审计和 V3 对话决策卡。0.6.0 移除小判别模型、推理 worker、模型接口、强制评估回执和分类器设置面板。

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
       Hook 观察严格选项回复 → V3 Ledger 与版本历史
```

Hook 不负责语义分类。`coding_request()` 仅提供正向提示，匹配失败不阻止生成句柄。句柄本身不要求发卡或调用工具；普通解释与咨询直接回答。已有待答卡的回复优先关联到原任务。

## 模块边界

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
- `audit.py` / `audit_web.py`：可选本地审计工作台，展示 audit.v1 的决定、引用、复核与报告；未扩展为 V3 界面。
- `buildchoice_mcp.py`：按需审计、决策卡与原生设置；无模型调用接口。

## 覆盖依据

`coverage` 与候选在同一次提取中形成，不安排第二轮 Agent 复核。只记录当前相关维度，最多六项，每项理由最多 300 字符。状态为 resolved / candidate / not_applicable / uncertain。

服务端核对来源是否真实读取、引用是否存在以及文件是否变化，并保存 `COVERAGE_RECORDED` 事件；最新一轮记录可由任务状态读取。Agent 声明保留为 `agent_declared`，`does_not_establish_completeness=true`。即使零候选也可保存依据。没有提交 coverage 的旧请求明确显示 reported=false。

覆盖元数据不进入候选分流，不会单独发卡、阻塞执行或授予操作权限。文件引用有效也不证明 Agent 对“已有答案”或“不适用”的解释正确。

## 账本与证据

audit.v1 保留 sessions、sources、decisions、reviews、events；V3 保留独立任务、候选、确认、上下文、激活卡、幂等操作和事件表。新增覆盖记录复用事件表，不增加数据库迁移。

工具实际读取文件，保存内容与 SHA256。JSON pointer 核对结构化字面值；精确文本引用检查原文是否存在，解释仍需复核。文件变化会使旧复核指纹失效。确认来自当前会话有效卡片的严格回复，Agent 转述不升级为可信确认。

## 实现关联

Agent 在原有开发过程中顺带登记决定与实现文件、可选行号、简短关系说明。服务端读取真实文件并保存 SHA256，使用 IMPLEMENTATION_LINKED 事件保存历史。无需第二轮审查或 Git 子进程。

状态查询重新核对文件；决定版本变化或文件变化时标记对应关联待复核。provenance 始终为 agent_reported_implementation，不能从“哈希未变”推断实现正确。旧确认、审计和事件不受影响，不增加数据库表。

## 安装与范围

决策落实验证复用 V3 事件与幂等操作表，新增独立 acceptance.v1 / verification.v1 契约。验收条件为 Agent 推导；本地采集执行为 collector_observed_execution；静态引用为 collector_file_read，三者不替代用户确认。历史 verdict 与当前 applicability 分开；相关输入变化后 current_pass=false。详见 [验证使用说明](DECISION_VERIFICATION.md)。

Python 包、插件 ID、MCP 服务键统一为 `buildchoice`。安装数据使用 `~/.buildchoice`，项目账本使用 `.buildchoice_audit`。插件只注册 UserPromptSubmit Hook；宿主权限审批与 Hook 信任保持独立。

模式 off 停用提示、MCP 审计和决策卡；显式启动的审计 CLI/网页仍可独立使用。升级方式见 [升级说明](UPGRADING.md)。
