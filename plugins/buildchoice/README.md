# BuildChoice · Codex 插件

BuildChoice 帮助 AI 编程用户掌握影响产品行为的重要实现选择。它结合需求与项目文件识别候选决策，在需要时解释可选方案与取舍；用户确定后，保存选择、关联相关代码，并在同一项目的后续聊天中复用。

## 功能

- **主动决策引导**：Agent + Skill 识别关键选择，MCP 根据证据与当前开发阶段确定是否需要询问，避免因普通技术细节打断用户。
- **对话决策卡**：在原 Codex 对话中展示选项、影响和建议，Hook 关联真实回复，保留修订历史。
- **项目决策记忆**：已确认选择形成项目参考；支持长期规则、普通参考 30 天归档、遗忘与恢复，遇到范围变化或冲突时重新确认。
- **实现关联与落实检查**：记录决定关联的代码位置，并可依据选择形成行为条件，辅助核对功能实现。

## 安装

从插件目录执行，`--workspace` 指向已有项目目录：

```bash
python setup.py --workspace /absolute/path/to/project --runtime-root /absolute/path/to/BuildChoice --install
```

安装后在仓库根目录启用决策卡：

```bash
python scripts/buildchoice_decisions.py pilot
```

默认采用 Prompt-first，决策卡独立开启。安装器会配置本地依赖，Hook 信任由 Codex 正常审批。决策历史保存在项目的 `.buildchoice_audit` 目录，不自动上传。

更多用法参见仓库根目录 [README](../../README.md)、[决策卡使用指南](../../docs/DECISION_GUIDANCE.md) 和 [决策记忆指南](../../docs/DECISION_MEMORY.md)。
