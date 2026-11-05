# 02｜参数字典：位置、含义、单位、常见起点及代价

> **数值区间是经验探索起点，不是模型或框架保证的最佳范围。** 实际值受模型尺寸、样本 token 分布、任务难度、资源和库版本共同影响。仓库运行时由 `configs/local/E00X.json` 等实验副本覆盖模板；先看 `runs/train/E00X/config.json` 确认最终生效值。

## A. 仓库配置字段（`configs/cpu-long.json`）

| 字段 | 当前仓库模板 | 含义 / 单位 | 学习时可探索的值 | 决定因素、观测量 |
|---|---:|---|---|---|
| `model_id` | Qwen2.5-Coder-0.5B-Instruct | 基础模型标识 | **非数值参数**；对比模型另建 lock | 能力、tokenizer、上下文长度、内存 |
| `model_lock` | `models/model-lock.json` | 精确模型修订 | 每个模型分别保存 | 防 B0/B1 权重漂移 |
| `data` | `[B002.jsonl]` | 训练 JSONL 文件列表 | 由审核批次决定 | 样本数、独立家族、质量、领域覆盖 |
| `exclude_manifests` | `[]` | 训练前排除的冻结基准清单 | 已冻结基准应填写对应路径 | 防数据泄漏；空列表不代表已检查 |
| `max_length` | 8192 | 单个训练序列 token 上限（prompt+target） | 2048/4096/8192 等，先审计长度 | 长序列峰值内存、训练耗时、模型上下文 |
| `max_steps` | 30 | optimizer 更新次数 | 用户本次实验为 112；不要盲套区间 | 样本数 × 目标 epoch ÷ 有效 batch |
| `learning_rate` | 1e-4 | 优化器基础 LR | LoRA 可试 5e-5、1e-4、2e-4 | loss 稳定性、过拟合、有效 batch |
| `gradient_accumulation_steps` | 1 | 几个 micro-batch 累积一次更新 | 1/2/4/8 | 平滑度、每 step 时间、总 updates |
| `threads` | 16 | PyTorch CPU 计算线程 | 8/16/32（本机实际压测） | CPU 配额、NUMA、吞吐/争用 |
| `seed` | 42 | 随机初始化/顺序种子 | 42/43/44 | 检验结果稳定性；不保证跨硬件确定性 |
| `lora_r` | 8 | LoRA 低秩矩阵的秩 | 4/8/16/32（逐项测试） | adapter 容量、trainable 参数数 |
| `lora_alpha` | 16 | LoRA 缩放 | 通常在固定 r 时试 α=r、2r 等 | `α/r` 与 LR 共同影响有效更新 |
| `target_modules` | `q_proj,v_proj` | 适配模块名称 | q/v 或 Attention+MLP 全线性层 | 可训练参数数、模型架构、计算成本 |
| `attn_implementation` | sdpa | Attention 实现 | sdpa/eager，需支持 | CPU 兼容性、内存、速度 |
| `gradient_checkpointing` | true | 重算激活以省内存 | true/false（只有资源允许才试） | 序列长度、RAM、训练吞吐 |
| `generation` | `{}` | 透传 `model.generate()` 参数 | 仅做独立实验，如 repetition_penalty | 输出循环、长度、任务复现 |

仓库当前模型以 FP32 CPU 运行；`max_length=8192` 是“上限并拒绝超长”而非固定补齐到 8192。`collate()` 只补齐当前 batch 的最长序列，batch=1 时几乎无需补齐。

### 不能仅凭配置求出的数值

- **effective epochs**：必须知道真实训练样本数 `N`；公式见第 03 章。
- **训练 token 总量**：必须知道真实各样本长度、采样顺序、实际 step/grad accumulation。
- **峰值内存**：必须实测，包括前反向激活、Attention 路径、LoRA 状态、进程与容器限制。
- **合适的 learning rate/rank**：没有仅依赖参数规模的万能公式；用曲线与独立基准判断。

## B. 在 `scripts/train.py` 写死、但值得认识的参数

| 参数 | 当前值 | 含义 | 可能实验方向 |
|---|---|---|---|
| `per_device_train_batch_size` | 1 | 单设备每次训练的样本数 | 增大需要 RAM；与 accumulation 相乘决定有效 batch |
| `use_cpu` | true | 在 CPU 上训练 | GPU 需整体重新评估性能、精度与配置 |
| `fp16 / bf16` | false/false | 关闭半精度训练 | 当前 FP32，勿只改 flag 就假定 CPU 硬件支持 |
| `optim` | adamw_torch | AdamW 优化器 | 先固定；优化器改变会影响收敛及状态内存 |
| `logging_steps` | 1 | 每一次 step 记录日志 | 训练很长时可增大以降低日志量 |
| `save_strategy` | no | 不保存中间 checkpoint | 教学期可考虑保存；需要修改代码 |
| `report_to` | none | 不上报第三方训练平台 | 保留本地可复现日志 |
| `gradient_checkpointing_kwargs` | use_reentrant=false | checkpoint 的调用方式 | 目前兼容配置，不是模型质量超参数 |
| `dataloader_num_workers` | 0 | 数据加载 worker 数 | 当前数据已预编码，小规模通常不是瓶颈 |
| `dataloader_pin_memory` | false | 不锁页内存 | CPU-only 配置 |
| `label_names` | ["labels"] | loss 标签字段名 | 与 `encode_sample` 保持一致 |
| `lora_dropout` | 0 | LoRA 路径上的 dropout | 0/0.05/0.1 作为将来的过拟合实验 |
| `do_sample` | false | 贪心确定性解码 | 现有生成固定；改变后 B0/B1 必须重跑 |

未显式设置的 Trainer 参数由锁定的 `transformers==4.57.1` 决定。例如，当前未传入 `warmup_steps`、`warmup_ratio`，因此没有 warmup；学习率调度按该版本默认的线性策略。**若升级库，应重新读取有效训练参数，不应把本文当作新版本权威文档。**

### AdamW 学习要点

AdamW 不仅接收梯度，还维护历史一阶/二阶动量，并使用权重衰减。学习时区分：
- `learning_rate`：每步参数更新尺度；
- `weight_decay`：正则项；
- `betas`、`eps`：优化器动量与数值稳定性；
- `lr_scheduler_type`：随着 step 改变 LR；
- `warmup_steps`：初期逐渐升高 LR。

上述后四项本仓库未显式指定，不要把“库默认值”误写成项目主动调参决策。可通过实际 `TrainingArguments` 输出确认精确默认数值。

## C. 生成参数（`scripts/bench/run_generate.py` / `scripts/generate.py`）

| 参数 | 默认/现状 | 与训练的区别 |
|---|---|---|
| `--max-new-tokens` | benchmark 默认 2048 | **新生成的** token 上限，独立于训练 `max_length` |
| `do_sample` | false | 贪心解码，适合可复现的代码实验 |
| `generation` | 空字典 | 透传额外 generate 配置，例如 `repetition_penalty` |
| `pad_token_id` | tokenizer.eos_token_id | 填充 token，不代表提前停止 |
| EOS | 模型 generation config | 正常终止条件之一；未遇 EOS 而用完 max_new_tokens 记为达到上限 |
| `--adapter` | B0 不传、B1 指向训练 run | B0/B1 同基座权重 + 同生成配置 |

当前代码没有在 `run_generate.py` 显式配置 temperature/top_p/top_k；在 `do_sample=False` 时，不应通过更改采样温度解释实验差异。

## D. 关系图：改哪个参数会影响什么？

| 目的 | 直接相关参数 | 典型副作用 | 不应误用的指标 |
|---|---|---|---|
| 延长训练 | max_steps / epoch | 时间增加、可能过拟合 | 只看 final train loss |
| 增加梯度稳定性 | micro-batch / accumulation | 更新次数、速度、内存可能变化 | “112 steps 永远等于同样样本曝光” |
| 提高适配容量 | LoRA rank/target modules | trainable params、训练耗时增加 | “rank 越大一定越好” |
| 处理长序列 | max_length/checkpointing | RAM、吞吐改变 | “模型上下文越长就越聪明” |
| 减少代码截断 | max_new_tokens | 推理时间与输出成本增加 | “未截断就业务正确” |
| 训练不稳定 | LR、scheduler、warmup | 收敛轨迹改变 | 单个 loss 数值 |
| 改善业务正确性 | 数据质量、任务输入、模型容量、优化配置 | 需独立评测 | 训练集准确率 |

## E. 参数调整纪律

1. 先复制实验配置，绝不覆盖上一轮运行目录。
2. 记录唯一主变量和其预测影响；如果需要同时改多个参数，标注“组合实验，不能单独归因”。
3. 先用 2 steps 冒烟验证内存与 loss 计算链路。
4. 正式训练至少保存生效 config、data manifest、model lock、metrics、adapter、benchmark scores。
5. 需要调整 Trainer 源码里的默认参数时，先新增配置项，再写测试；避免“改了库默认值却无法复现”。

参考：`docs/02-training.md`、锁定版本的 Transformers/PEFT 文档（仓库 README 链接）。
