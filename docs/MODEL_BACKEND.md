# 可选分类器接入

默认 Prompt-first 和证据审计不需要模型。本仓库同时保留 `PredictorBackend`、本地 worker、字段级 NLI 与证据路由实现，供独立部署模型资源时使用。

字段状态为 required（本次所需）、resolved（证据已定）和 indexed（资料覆盖）。固定集合策略将这些状态组合为 PASS、INSPECT、ASK 建议。

## 资源要求

模型资源在 Git 仓库之外部署：

- 本地 Hugging Face 基座与 tokenizer；
- 匹配的 LoRA 适配器；
- 后端清单：基座与适配器目录、逐文件 SHA256、输入投影版本、阈值和源码哈希；
- `configs/codex_desktop_gate.toml` 中相应后端设置。

清单必须与当前部署源码匹配。研究工作区旧清单包含额外的研究文件哈希，不能直接作为该源码仓库的部署清单。仓库没有附带模型权重或为其声明可直接启动的默认配置。

模型依赖包括 PyTorch、Transformers、PEFT 和 SentencePiece；根据目标设备安装 PyTorch 后，再安装 `requirements-model.txt`。

```toml
[backends.mdeberta_v10]
factory = "clarification_gate.backends.nli:NliBackend"
manifest = "artifacts/gate_models/mdeberta-v10/1/model_manifest.json"
manifest_sha256 = "<actual-manifest-sha256>"
device = "cpu"
```

目录和文件哈希由部署者从实际资源生成。资源、清单和配置一致后，使用 `scripts/manage_desktop_gate.py start` 启动 worker，并选择自动或强制调用模式。主 Agent 负责实际读取资料、向用户提问和执行。
