# 01｜从测试脚本样本到 LoRA adapter

## 1. 本项目的真实数据流

```text
data/private/train/B002.jsonl（用户审核通过）
   │ 每行 inputs + target
   ▼
common.load_data()                 验证 split/source_group/target 语法等
   ▼
common.messages()                  system + 五段 user 输入
   ▼
tokenizer.apply_chat_template()    chat template → token ID
   ▼
common.encode_sample()             input_ids / attention_mask / labels
   │ labels：prompt 为 -100，assistant 答案对应 token ID
   ▼
train.py: Trainer + PEFT LoRA       只更新 adapter 参数
   ▼
runs/train/E001/adapter/           保存 adapter + tokenizer
   ▼
generate.py: 基础模型 + adapter    贪心生成代码
   ▼
bench: score / compare             评估代码形式、框架、剧本匹配
```

训练和生成共用 `messages()`，避免训练/推理输入格式不一致。生成并不执行 Python 脚本；本项目 L3 执行和 L4 人工评审是独立阶段。

## 2. SFT 的优化目标

给定提示 `x` 和目标测试脚本 token `y=(y1,...,yT)`，使用 teacher forcing 最小化目标输出 token 的负对数似然：

```text
L = - (1/T) × Σ_t log Pθ(y_t | x, y_<t)
```

此式是简化表达：实际实现按 Trainer/模型处理的有效标签位置求损失（包含 token 归一化细节）。`-100` 在 PyTorch 交叉熵中表示忽略该位置的损失。**目标 token 是监督信号，不是每个 step 只生成一个 token。**

`encode_sample()`：
- `prompt = tokenizer.apply_chat_template(messages(row), add_generation_prompt=True)`
- `full = ... messages + assistant target ...`
- 检查 `full[:len(prompt)] == prompt`，防止不同聊天模板拼接出错误标签位置。
- `labels = [-100] * len(prompt) + full[len(prompt):]`。
- 不做静默截断：`len(full)>max_length` 直接报错。

**思考题**：训练 loss 低，能否保证调用的是正确业务 API？不能。逐 token 监督与整段代码的业务可执行性是不同目标。

## 3. 基础权重和 LoRA

标准线性层：`h = W x`。LoRA 对固定 `W` 附加低秩更新 `ΔW = (α/r) BA`，其中 `A ∈ R^(r×in)`，`B ∈ R^(out×r)`。

每个受 LoRA 适配的线性层：
- 全参数增量需要 `out × in` 个参数；
- LoRA 的新增参数约为 `r × (in + out)`，再乘层数求总数；
- `r` 是低秩容量；`α/r` 控制适配更新的缩放强度，不等于学习率；
- 基础模型参数仍需加载，长序列激活仍要占内存。

当前 `target_modules=["q_proj","v_proj"]`，不会自动覆盖所有 Attention/MLP 线性层。`scripts/train.py` 写入 `parameters.json`，应以实测 `trainable` 和 `total` 为准。

## 4. 一次 optimizer step 发生了什么

```text
取 micro-batch（当前 1 条）
 → forward（计算目标 token 的 logits 和 loss）
 → backward（LoRA 参数梯度）
 → 累积 gradient_accumulation_steps 次
 → optimizer.step()（一次实际更新）
 → scheduler.step()（调整学习率）
 → 清理梯度、进入下一次更新
```

当前 `TrainingArguments` 使用 `optim="adamw_torch"`、`max_steps`、`learning_rate`、`gradient_accumulation_steps`。`gradient_checkpointing=True` 使部分激活通过重算换内存。实际每一步涉及的 batch、token 长度可能不同，因此时间与内存不能仅由 step 数推断。

## 5. Trainer 的职责和不做的事

**当前代码做了：** 读完整数据至内存、固定 micro-batch=1、CPU、FP32、按 `max_steps` 停止、每步写 loss/grad_norm/lr、训练结束保存 adapter、检测适配参数变化。

**当前代码没有做：**
- 没有独立验证集的 eval loss；
- 没有中间 checkpoint；
- 没有自动早停；
- 没有超参数搜索；
- 没有将 API 业务执行结果直接反馈给 optimizer；
- 没有 DPO/RL/PPO/GRPO、量化训练或多卡训练。

因此“默认参数训练”不准确：代码明确覆盖了一部分 Trainer 默认值，同时保留另一些默认值（例如 scheduler 和 warmup）。学习时一定要区分“代码明确指定”与“库版本默认行为”。

## 6. 训练与推理的差异

| 维度 | 训练 | 推理 |
|---|---|---|
| 输入 | prompt + 标准答案 | prompt |
| 目标 | 降低标准答案 token 的损失 | 自回归生成新 token |
| 模式 | 更新 LoRA 参数 | `torch.inference_mode()`；不更新权重 |
| token 上限 | `max_length` 限制整条（prompt + target）训练序列 | `max_new_tokens` 限制新生成 token |
| 显存/内存 | 权重、梯度、优化器状态、激活 | 权重、KV cache、生成缓存等 |
| 产物 | adapter + 日志 | 候选代码 + records |

训练采用 `model.config.use_cache=False`，推理中设置为 `True`。具体生成的停止行为需结合 EOS 与 `records.json` 的 `hit_token_limit` 看。

## 7. 参数和输出的一致性

- 训练与 B0/B1 应用相同 model lock/tokenizer/chat template；
- B0 与 B1 的生成设置（例如 `max_new_tokens`、贪心解码）一致；
- adapter 的 `model-lock.json` 与生成基座的版本匹配；
- 同一 benchmark suite 及 scorer 版本，才有严格可比性；
- 真实私有样本、权重、生成文件仍保存在 gitignore 的目录内，不应将其复制到学习文档。

参考：仓库 `scripts/common.py`、`scripts/train.py`、`scripts/generate.py`。
