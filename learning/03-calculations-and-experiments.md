# 03｜从公式计算到实验：以 max_steps=112 为例

> **已知事实**：仓库默认 `max_steps=30`，用户正在服务器上将其改为 **112** 重新训练。以下例子只推导理论量；除非从 `runs/train/...` 读取真实文件，否则不能声称实验跑了几轮、花了多少时间或效果提高。

## 1. step / batch / epoch 如何换算

定义：
- `N` = 训练池有效训练样本条数（不是 JSONL 原始行数的猜测）；
- `b` = 每个设备的 micro-batch size（当前 1）；
- `g` = gradient accumulation steps（当前 1）；
- `w` = 并行参与训练的数据进程数（当前单 CPU 进程，按 1）；
- `S` = optimizer 更新次数（现改为 112）。

近似有效 batch：`B_eff = b × g × w`。

理论样本曝光量（按常规完整 batch）：
`E ≈ S × B_eff`。

近似 epoch：
`epochs ≈ S × B_eff / N`。

由于 dataloader 会在轮末处理不足批量、Trainer 的跨 epoch 迭代行为等细节，**以上是用于规划的近似式**。实际记录的 `status.json.epochs` 在本仓库也是用 `S × g / N` 计算出的值；它不是通过逐样本 ID 统计的实际遍历次数。

### 112 steps 的情景表（b=g=w=1）

| 如果实际 N 是 | 30 steps 约等于 | 112 steps 约等于 | 说明 |
|---:|---:|---:|---|
| 28 | 1.07 epoch | 4.00 epoch | 小数据可能重复许多次 |
| 40 | 0.75 epoch | 2.80 epoch | 112 已经超过两轮 |
| 56 | 0.54 epoch | 2.00 epoch | 只是假设，不是 E001 已知样本数 |
| 70 | 0.43 epoch | 1.60 epoch | 尚未满两轮 |
| 112 | 0.27 epoch | 1.00 epoch | 正好一轮的理想情况 |

**先读取 N，再解读 112。** 不存在“112 steps 比 30 更科学”的通用结论。

### 如果改成 g=4

保持 `b=1,w=1`，同样 112 steps 将计划处理约 `112×4=448` 次样本曝光，不再与原来的 112 steps 公平比较。

如果目标保持原先 `112×1=112` 次曝光，则 `S_new≈112/4=28` steps。**注意**：虽然曝光量近似相同，但梯度合并方式、更新次数和 LR scheduler 时间轴不同，结果仍不应认为完全等价。

## 2. max_steps 和学习率调度关系

当前 `TrainingArguments` 未配置 warmup，默认采用线性衰减（以锁定的 transformers 版本为前提）。

概念公式（不计实现细节）：

```text
lr(step) ≈ lr_initial × (1 - step / max_steps)
```

若初始 LR 是 `1e-4`，在 30 和 112 steps 的**相同步数**下，学习率不是一样的：

| 训练进度 | S=30 时理论 LR | S=112 时理论 LR |
|---|---:|---:|
| 初始 | 1.0e-4 | 1.0e-4 |
| 第 15 次更新后 | 5.0e-5 | 约 8.66e-5 |
| 第 30 次更新后 | 约 0 | 约 7.32e-5 |
| 训练完成 | 约 0 | 约 0 |

因此，**改 `max_steps` 不只是延长训练，还会改变每个固定 step 的学习率轨迹**。这不是“仅增加 82 次同样大小的更新”。下次如要隔离训练量效应，可考虑固定 scheduler 设计、保存中间 checkpoint；这需要修改现有代码并另立实验版本。

最终应看 `metrics.jsonl` 实际 `learning_rate`，以上表格不是日志原值。

## 3. token 长度如何影响代价

每条数据的 `L_i = prompt_tokens_i + supervised_tokens_i`，训练完整序列都会进入 forward；只有监督 token 对 loss 直接贡献。平均每步耗时不能只看监督 token 长度。

粗略理解：
- 权重内存随参数量与 dtype 字节数上升；
- 激活内存与 batch、序列长度、层宽、checkpoint 策略有关；
- 不同 Attention 实现会改变序列长度增长的性能/内存特征；
- 生成时 KV cache 一般随上下文加生成 token 数增长；
- **不能以 8192 × 112 计算训练 token 总量**：8192 是上限，实际样本长短不一，并且可能重复抽样。

估算训练 token 需要 `token-lengths.json` 和真实样本顺序/step 记录；只有长度列表时可以算平均和范围，不能精确重建每次 dataloader 抽到的行。

### LoRA 参数量估算

假设某个线性层输入/输出维度分别是 `d_in`、`d_out`，rank 为 `r`：
- 全矩阵元素：`d_in × d_out`；
- LoRA 元素：`r × (d_in + d_out)`；
- 例：若 `d_in=d_out=1024, r=8`，分别为 1,048,576 和 16,384（**仅为数学示例，不是 Qwen 模块的实测形状**）。

整体需遍历真实模型的目标层，不应把单层例子乘想象的层数；请读取 `parameters.json` 的真实 trainable 与 total。

### RAM/时间估算

以已记录的本机历史实测为参考：长序列 FP32 无 checkpoint 曾 OOM；启用 checkpoint 后一次历史试验的峰值约 22.5 GB。该数字不能直接推广到新的样本长度、线程和模型。训练总时长只能粗估为 `更新数 × 实测每步耗时`，不承诺线性，尤其初次加载、数据长度变化、CPU 争用都影响结果。

## 4. 学习曲线：112 steps 该如何看

不要只比较一个 final loss。

1. 先确认两次使用相同 model lock、数据 SHA、输入模板、LoRA rank/targets、LR、seed、梯度累积，以及训练源码版本。
2. 读取 `metrics.jsonl`：横轴为 update step，画 loss、grad_norm、learning_rate。比较前 30 个 step 的轨迹时记得 LR scheduler 已变化。
3. 看 `status.json`：是否 training_completed、`train_samples`、`epochs`、`adapter_max_abs_change>0`。
4. 看 `token-lengths.json`：最长样本、监督 token 比例和长度分布。
5. 固定同一 benchmark、生成配置、模型锁，对 B0/30-step B1/112-step B1 做逐任务比较。
6. 若出现退步，区分截断、语法、框架、API、断言、身份复制；不要只看 `auto_pass`。

### 简单日志分析脚本（只读本地运行文件）

```python
import json
from pathlib import Path

run = Path("runs/train/E001-112")  # 换成真实运行目录，不要猜路径
status = json.loads((run / "status.json").read_text(encoding="utf-8"))
cfg = json.loads((run / "config.json").read_text(encoding="utf-8"))
lengths = json.loads((run / "token-lengths.json").read_text(encoding="utf-8"))
metrics = [json.loads(s) for s in (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]

print("status:", status)
print("configured steps:", cfg["max_steps"], "effective N:", status.get("train_samples"))
print("supervised tokens total (one nominal pass):", sum(x["supervised_tokens"] for x in lengths))
print("sequence max:", max(x["input_tokens"] for x in lengths))
for row in metrics:
    if "loss" in row:
        print(row.get("step"), row["loss"], row.get("grad_norm"), row.get("learning_rate"))
```

注意：上面的 `supervised_tokens total` 是**对训练池每条样本求一次和**，不是整个 112-step 运行实际监督 token 总量。

## 5. 初学者容易踩的坑

| 错误理解 | 正确理解 |
|---|---|
| steps 乘 3.7，训练质量应同比提高 | loss、泛化与 steps 不线性，可能过拟合 |
| 增大 max_length 就能输出更多代码 | 生成上限由 `max_new_tokens` 决定 |
| LoRA rank 变大就一定更会写业务逻辑 | 更大容量可能也更容易记住错误 target |
| loss 降低说明模型没有漏断言 | 逐 token loss 与功能正确性是不同指标 |
| 学习率 1e-4 是 Qwen 官方最优 | 只是合理起点，受数据和优化设置影响 |
| 112 steps 与 30 steps 只有更新次数不同 | 线性 LR schedule 的轨迹也改变 |
| 训练和评测使用同一数据能更稳 | 会引入数据泄漏，不能证明泛化 |
| 14/14 都没有 auto_pass 就没有学习 | 需要看各层质量、逐任务差异和执行情况 |

## 6. 本轮实验记录模板

```markdown
# E001-112：训练量观察
- 实验目的：将 max_steps 从 30 改为 112，观察损失/生成变化
- 模型 lock/revision：
- 代码 commit：
- 生效配置：runs/train/.../config.json
- 训练池 SHA / N / source_group 数：
- batch × accumulation × process：
- 理论 epoch：
- status / 实际 steps：
- loss 曲线与 learning_rate 轨迹：
- grad_norm 异常：
- adapter_max_abs_change：
- benchmark suite/manifest/scorer：
- 生成 max_new_tokens：
- B0 与 B1 按层和逐任务变化：
- 不能归因的因素（如 LR schedule 同时变化）：
- 下一轮**唯一主变量**及可证伪预测：
```
