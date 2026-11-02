# 项目资料读取观察

V3 pilot 在 UserPromptSubmit 之外注册 PostToolUse。事件与字段依据 [Codex 官方 Hook 文档](https://learn.chatgpt.com/docs/hooks)：使用 cwd、session_id、turn_id、tool_name、tool_use_id、tool_input、tool_response；Bash 在失败时也会触发，因此不能把触发事件本身当成已读。Hook 不阻塞工具、不改写结果、不改变执行权限。

当前只支持以下窄范围读取：

- Bash：单文件 cat、cat --、sed -n '起行,止行p'，以及 Get-Content [-LiteralPath/-Path] 路径，可接固定 Select-Object -Skip N -First M 范围选择。路径必须是字面值；多命令、变量、重定向和复杂脚本均跳过。
- mcp__filesystem__read_file / read_text_file：path 和可选 head；仅单条 text 返回，不推断 tail、图像或多文件输出。

Shell 必须有明确的结束状态和退出码 0（结构化 JSON 或可识别的原生输出头）；运行中、报错、截断和未知返回格式跳过。MCP isError 也会被拒绝。读取器比较真实返回文本与当前文件对应行，只有完全一致才登记。只处理项目内、非链接、非私有路径的 UTF-8 文件，沿用审计读取器 256 KiB 上限；空输出不登记。换行只归一 CRLF，允许工具附加一个末尾换行。

记录复用 sources、sessions、events，无新增表或后台程序。sources.content 为空，只保存相对路径、全文件 SHA256、起止行、返回片段哈希、工具名/调用 ID 和宿主会话/轮次摘要；不保存原始工具参数、完整输出或聊天正文。私有目录和 .env 等文件沿用审计读取器排除规则；这不是任意文件中敏感信息的自动识别器。

Hook 给出 source_id；buildchoice_decision_status 的 observed_reads 也返回当前聊天最近至多 30 条记录及 current。INSPECT 优先检查对应路径的真实读取记录。整文件当前记录可消除“未读”状态；部分读取只有实际引用在已返回范围内才可支持相关资料，不能引用范围外原文或使用全文件 JSON pointer。文件版本变化会失效，新增相关读取记录会使旧筛选缓存失效，需新幂等键重筛。

这只证明工具返回过对应内容，不证明 LLM 理解了文件，也不自动证明产品约束已经解决或用户已经确认。含糊/冲突证据仍先 INSPECT；不支持的工具、格式或范围继续用 buildchoice_audit_read 显式采集，不要求全项目扫描或覆盖所有读法。

插件更新后需重新加载并按宿主要求审阅、信任变更后的 Hook 定义；安装器不会自动信任。诊断中的原有用户确认 Hook 状态不代表所有读取工具已经过端到端验证。测试使用合成回调验证接收与证据边界，未在当前聊天中替换已安装 Hook。
