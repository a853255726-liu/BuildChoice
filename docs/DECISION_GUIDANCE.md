# BuildChoice · 决策卡使用说明

V3 是独立试验功能，默认关闭。旧 Prompt-first、四种调用模式和 audit.v1 继续可用。主 Agent 发现候选，服务端筛选，用户在原对话逐张回答；不需要卡片网页。

## 开关

```bash
python scripts/gate_decisions.py settings
python scripts/gate_decisions.py pilot
python scripts/gate_decisions.py model-on
python scripts/gate_decisions.py model-off
python scripts/gate_decisions.py off
```

也可使用原生设置的“V3 关键决策引导”和“V3 NLI 第二意见”。两个开关与旧模式解耦，关闭 V3 不改变旧模式。V3 不会为了取得分类器回执擅自开启旧 required 模式。

## 对话流程

1. 受支持的 UserPromptSubmit Hook 提供本轮短期 `cg-v3-ctx-...` 句柄。
2. 主 Agent 使用 `decision-discovery` Skill，读取直接相关资料，再提交候选；零候选直接继续。
3. INSPECT 先读资料；DEFER 留到相关依赖；ASK_NOW 每次激活并展示一张卡。
4. 用户明确回复 A/B 或卡号加“选 A”。同会话、未过期、当前版本的一张待答卡，才由 Hook 记录观察到的选择。
5. 自由回答、混合指令和“解释一下”不自动确认。用户改变选择则创建新 revision，再明确确认。

“激活”不证明 UI 实际展示。缺少受信任 Hook 时可以正常聊天，但产品记录保持 `agent_reported_unverified`，没有把 Agent 转述升级为可信确认的 MCP 接口。

## 本地模型

仓库不包含模型权重。V3 可复用独立安装的冻结 NLI 运行时，在本地配置 `configs/decision_v3.json`：

```json
{
  "config_version": 1,
  "mode": "pilot",
  "model_check": "on",
  "context_ttl_seconds": 900,
  "model_runtime": {
    "python": "/absolute/path/to/runtime/bin/python",
    "root": "/absolute/path/to/frozen-runtime",
    "config": "/absolute/path/to/frozen-runtime/configs/codex_desktop_gate.toml"
  }
}
```

该文件属于本地运行配置，不应提交个人绝对路径。NLI 在独立进程加载原后端，不改变权重、阈值、源清单或原 worker；保留真实 margin scores、阈值和版本。分数不是已校准的正确概率。

只处理 2/3 个真实不同字段的批次。单候选、多未读资源、超长证据明确标为不支持，不补字段、不截断。未部署模型则返回 NOT_READY，规则路径继续工作。

## 迁移与回退

```bash
python scripts/gate_decisions.py --workspace /path/to/project migrate
```

首次增加独立 V3 表前会保存 SQLite 备份，不改变 audit.v1 决定或 reviews 的含义。关闭 V3 即可停用，无需回滚。

如果确实要移除 V3 表，先关闭 pilot、停止相关会话，再显式运行：

```bash
python scripts/gate_decisions.py --workspace /path/to/project rollback
```

回退先完整备份当前数据库，再只移除 V3 表；迁移之后新写入的 audit.v1 记录仍保留。备份包含 V3 历史，请按自己的数据保留规则管理。

## 信任与范围

句柄关联到本地受信任宿主 Hook 回调及其实际输入。它不是防御能任意修改本用户数据库、执行本地回调的恶意程序的密码学边界。原生工具权限和审批始终独立。

默认只保存任务摘要、消息哈希、选项和状态，不无差别保存聊天全文。候选和主动审计的文件内容仍可能包含用户主动提交的信息；不自动上传。
