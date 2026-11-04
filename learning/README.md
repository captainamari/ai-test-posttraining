# Post-training 学习路径（以 ai-test-posttraining 为实验台）

> 版本：2026-11-04。对应仓库 v0.1；以 `scripts/train.py`、`scripts/common.py`、`scripts/generate.py` 与 `configs/cpu-long.json` 的实际实现为准。本文为学习材料，不声称 E001 已取得业务质量提升。

## 目标与边界

学习对象是 **Qwen2.5-Coder-0.5B-Instruct + CPU FP32 + SFT/LoRA + 存量测试脚本重建的监督数据**。目标不是立即选择最佳业务模型，而是能够独立解释每个参数、完成可复现实验，并基于日志提出有证据的下一轮假设。

本目录不更换模型、不改训练架构、不覆写当前实验、不上传 `data/private/` 或 `runs/`。学习内容与项目现有 `docs/00-runbook.md`（操作流程）、`docs/01-data.md`（样本治理）、`docs/05-benchmark.md`（评测合同）互补。

## 建议学习顺序

| 阶段 | 阅读 | 要能够回答的问题 | 实际产出 |
|---|---|---|---|
| S0 基本链路 | [01-训练链路与核心概念](01-training-pipeline.md) | 哪些权重改变，loss 从哪里计算，训练和推理有何区别？ | 一张从 JSONL 到 adapter 的路径图 |
| S1 配置字典 | [02-参数手册](02-parameter-reference.md) | 每个字段在哪里设置，影响显存/时间/收敛中的哪一项？ | 一份逐字段解释的实验配置 |
| S2 量化实验 | [03-计算与调参实验](03-calculations-and-experiments.md) | 112 steps 对应多少 epoch、token 和更新？ | E001-112 训练审阅记录 |
| S3 数据和评价 | [04-数据、评测与故障归因](04-data-evaluation.md) | loss 下降为什么不等于脚本能用？ | 分层对比和下一轮单变量假设 |

## 建议学习方式

1. 先读公式，再定位源码，最后读取自己运行目录中的 **真实值**。
2. 将“代码确认的事实”、“经验起点”和“尚待实验验证的假设”分开记。
3. 每轮只改变一个主要因素；若改模型、提示结构、训练池、评测器，则标明哪种比较仍然有效。
4. `max_steps=112` 已在服务器训练中：**不要中断或改动该实验**。先保留运行目录，结束后再观察其 logs 和 B0/B1 对照。
5. 以能解释“为什么变化”作为考核，不以一次 pass 数的涨跌作为全部结论。

## 源码索引

| 关注对象 | 代码位置 |
|---|---|
| 配置加载、Trainer、LoRA、日志 | `scripts/train.py` |
| 五段输入与聊天模板、completion-only 标签 | `scripts/common.py:messages/encode_sample` |
| 模型加载与生成 | `scripts/generate.py:load_model/generate_items` |
| 基准上运行推理 | `scripts/bench/run_generate.py` |
| 静态评分与 Oracle | `scripts/bench/benchlib.py` |
| 实验模板 | `configs/cpu-long.json`（服务器每轮应复制到 `configs/local/`） |
| 实验产物 | `runs/train/<实验>/`、`runs/bench/<suite>/<实验-arm>/` |

## 术语索引

- **pre-training**：在大规模语料上建立基础语言/代码能力；本项目不做。
- **post-training**：基础模型之后的能力对齐、适配过程，含 SFT、偏好优化等；本项目只实现 **SFT + LoRA**。
- **SFT**：使用输入与期望输出对计算监督损失。
- **PEFT / LoRA**：冻结大部分基础权重，仅更新低秩适配参数。
- **step（optimizer update）**：优化器更新一次；不等同于单样本或单次 forward。
- **micro-batch**：单次前反向计算的数据批大小，当前固定为 1。
- **gradient accumulation**：累计多个 micro-batch 梯度后进行一次优化器更新。
- **epoch**：对训练池的平均遍历次数；在固定 max_steps 时可能出现不足/超过一个整轮。

## 自测题（先口述后验证）

1. 为什么 `max_steps=112` 不能单独说明“训练了几轮”？
2. 为什么 `loss` 可以下降但 `auto_pass` 不上升？
3. 当 `gradient_accumulation_steps` 从 1 改为 4、希望总样本曝光次数不变时，`max_steps` 应如何变化？
4. 为什么 `max_length=8192` 不代表生成时最多输出 8192 token？
5. 在当前 CPU FP32 实现中，LoRA 为什么节省可训练权重和优化器状态，却不能消除长序列激活内存？
6. 在拿到实际训练样本数、监督 token 长度、step 日志以后，如何判断 112 steps 是否已经足够？

**通过标准**：能在不猜测的前提下用配置、代码与 `runs/train` 的实际结果回答以上问题。
