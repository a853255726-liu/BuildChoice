# BuildChoice · 安装与更新

0.15.3 安装共同原则与按需专题分发、审阅包指导冻结、实际对象身份及证据引用修复。旧请求和历史包保持兼容。本地安装后的语义、成本及原生聊天证据分别记录；安装本身不证明审阅判断更准确。

0.15.2 增加按需加载的界面内容、文档一致性与故障排查参考，并把验证证据原则合并到已有检查。普通咨询和无关改动不加载专题，不增加固定阶段、确认卡、模型服务或全量审计；当前有效结果可复用。外部方法已按项目适配，未安装完整上游插件，来源与许可证随 Skill 分发。更新插件与运行包后重新连接 MCP；记录和接口保持兼容。

0.15.1 将独立审阅收敛到用户目标与已知约束下的实质偏差，允许合理实现空间；按重要疑点取证，普通低影响任务直接检查。不增加表单、合同字段、工具或模型服务，现有记录和接口兼容。更新运行包与 Skill 后重新连接 MCP。见[审阅范围](INDEPENDENT_REVIEW.md)。

0.15.0 增加[宿主独立上下文审阅](INDEPENDENT_REVIEW.md)：按任务启用 review_policy=independent，先保存独立首轮判断，再按具体疑问补背景并保留修订理由。发布反馈必须逐项处理发现。插件不调用模型，宿主继承同一模型与权限；隔离是宿主声明而非程序认证。无新模型依赖，无需迁移旧记录。请同时更新运行包和 Skill 并重新连接 MCP。

0.14.4 新反馈采用 behavior-feedback.v1 结构化内容与固定模板，区分开发前预期确认和开发后结果反馈。新增当前文件 inspect 与补充检查 supplement，不伪造旧预期/起点。主要展示使用变化、重要差异、具体且重要的检查缺口及自然语言入口；没有重要缺口时省略第三项，详细证据与例行限制保留在详情。新 create/supplement 输入需要 report 与 findings.display；旧记录保持可读。请同时更新插件和运行包后重新连接 MCP。见[反馈说明](FEEDBACK.md)。

0.14.3 增加原生回复的消息关联预检、严格单题表单匹配、结构化恢复结果及不含正文的 Hook 诊断。缺少新消息句柄时停止旧句柄与换接口重试；消息来源校验保持不变。提示策略异常不再阻止决定消息关联。需同时更新运行时和 Skill 并重新连接 MCP；无需迁移旧决定或重新确认已有选择。详见[回复关联与恢复](REPLY_BINDING.md)。

0.14.2 新候选使用 content_version=decision-content.v1，每个选项明确 risk_assessment。当前 MCP 提取/提议修订入口要求新契约；原有账本和已激活的旧卡保持可读。程序校验格式、明确重复、风险状态矛盾与来源，失败要求模型修正，不机械截断。原生标题只保留问题，宿主编号不再与 A/B 重复；补充理由保留在 details，有依据的低/中/高风险均可显示。未评估不等于无风险，格式通过不证明语义正确。请同时更新运行时与 Skill，并重新连接 MCP。生成规则见[结构化内容](DECISION_CONTENT.md)。

0.14.1 修正对话呈现：决策单卡/批次优先接宿主原生问题组件，保留固定文字降级；开发后以非技术语言对照原约定、实际行为与证据范围，补上任务阶段提醒。包含安装检查对 SDK Hook 枚举的兼容修正。无需迁移已有账本；更新运行包与插件后重新连接 MCP，使新指引和工具返回载荷同时生效。

0.14.0 增加正式的按任务产品预期、行为审阅和集中决策功能，四个入口同时提供于日常/完整工具集。旧 SQLite 增量增加附加表，无需重建旧决定或迁移单卡调用。请一起更新运行时和 Skill，并重新连接 MCP。快照正文写入安装数据目录的 product-snapshots，需位于源码工作区外；旧版不存在代码正文快照，不会补造旧任务历史。使用方式与边界见[产品审阅](PRODUCT_REVIEW.md)。

更新后重新连接 MCP。未配置 tool_profile 的项目使用日常工具集；需要独立审计或高级功能时，在原生设置切换“工具集：完整”，或执行 `python scripts/buildchoice_decisions.py full`。这不修改既有决定与确认历史。

自定义 MCP 调用方应按当前工具 Schema 提交候选，明确提供 suggested_action；不再提交 needs_user_choice、current_dependency、relevance、engineering_detail 或 why_user_choice。已有 SQLite 记录保持可读，重新提交或修订时使用当前字段。插件与运行时应一并更新，避免使用旧 Skill 生成已退出的字段。

## 从源码安装

需要 Python 3.11+、Git 和支持本地插件的 Codex。先准备已有项目目录，然后在 BuildChoice 仓库根目录执行：

~~~bash
python plugins/buildchoice/setup.py --workspace /absolute/project --runtime-root . --decision-mode pilot --install
~~~

安装器准备 Python 依赖，将插件副本与生成的配置写入安装数据目录，源码配置保持不变。默认数据目录为 ~/.buildchoice，可用 --data-home 指定其他位置。安装后重新连接 MCP 或重启 Codex，按宿主提示审阅 Hook 信任。

## 更新源码安装

1. 停止使用目标项目的 MCP 连接，备份项目的 .buildchoice_audit 目录及安装数据目录。
2. 更新 BuildChoice 源码，在仓库根目录重新执行安装命令：

   ~~~bash
   git pull --ff-only
   python plugins/buildchoice/setup.py --workspace /absolute/project --runtime-root . --install
   ~~~

3. 使用自定义数据目录时，继续传入相同的 --data-home；每个已登记项目分别运行安装命令。项目设置会保留，可按需使用 --decision-mode pilot 或 off 调整。
4. 重新连接 MCP，核对目标项目、运行时和开关。安装自检见[故障排查](TROUBLESHOOTING.md)。

项目账本保存在项目自身的目录中。更新插件不需要清空账本，也不需要重建已确认选择。

## 使用运行包

在源码目录运行 python scripts/build_distribution.py，可在 dist 中生成核心运行包、插件包及对应的 SHA256 文件。核对校验和，将插件包解压到独立目录，在其中执行：

~~~bash
python setup.py --workspace /absolute/project --bundle /absolute/buildchoice-core-VERSION.zip --decision-mode pilot --install
~~~

将 VERSION 替换为实际文件中的版本号。更新运行包安装时，先备份项目账本与安装绑定，再用独立的 --data-home 初始化并安装；不要覆盖正在使用的运行目录。项目设置保存在安装数据目录内，使用新目录后需要重新配置。

## 项目与运行模式

同一安装数据目录可以登记多个项目，各自保存绑定与运行设置：

~~~bash
python plugins/buildchoice/setup.py --list-projects
python plugins/buildchoice/setup.py --use-project /absolute/project
python scripts/buildchoice_decisions.py --workspace /absolute/project settings
python scripts/buildchoice_decisions.py --workspace /absolute/project off
~~~

切换后重新连接 MCP。关闭决策卡即可停止卡片流程，不需要删除项目数据。项目匹配、文件位置和独立配置见[项目使用与切换](PROJECTS.md)。

## 指导语维护与历史兼容（0.15.3）

0.15.3 集中维护共同原则与专业短版，增加 prepare_independent 的可选 review_topics、实际指导保存和身份披露。旧调用仍可省略专题；旧审阅包不追溯换指导，缺 guidance 的历史记录继续读取 legacy-0.15.2 原文。无需迁移或删除用户决定、历史审阅或失败结果。当前检查的开头精确限定为无正式前后对照，证据与 change_origin 合同不变。

维护时先运行 scripts/sync_guidance.py，再用 --check 检查生成块。生成脚本不随核心运行包执行；新 Python 指导模块按已有打包规则入包。发布包版本为 0.15.3。安装与结构核验不证明语义判断质量；实际结果、宿主链路和开销应分别验证和报告。

验证辅助 checks/guidance_case_manifest.py 的 capture 应在执行结束产生清单，反馈启动器使用 verify 校验 case、输出根目录与已列文件哈希后才准备快照；匹配失败即停，不能退回原项目。该清单不是签名授权或生产交付注册表，也不证明未列文件或用户语义。
