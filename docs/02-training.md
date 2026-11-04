# 训练、调参、调用模型、换模型

所有命令在工程根目录、已激活 `.venv` 时执行。每轮的完整清单见 [00-runbook.md](00-runbook.md)。

## 0 几个词

- checkpoint：某个版本的模型参数。起始模型和训练后的适配器都要记录版本。
- tokenizer：把文本转成 token ID 的工具；训练和推理必须用同一个。
- SFT：用审核过的目标输出监督模型。
- LoRA：冻结原模型，只训练少量附加矩阵（适配器）。推理时仍需要原模型 + 适配器。
- step：一次优化器更新。batch=1、梯度累积=k 时，一步消耗 k 条样本。
- epoch：训练池被完整看一遍。`epoch = max_steps × gradient_accumulation_steps ÷ 训练样本数`。
- loss：训练目标的数值，只说明"对训练样本拟合得怎样"，不等于生成脚本的业务正确率。

## 1 环境（已完成，换机器时参考）

```sh
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip            # Python 3.10 自带的 pip 23.0.1 装 torch 会报 flit_core 找不到
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m pip check
python -m unittest discover -s tests     # 24 项应全部通过
```

本机实测版本：torch 2.8.0+cpu、transformers 4.57.1、peft 0.17.1、accelerate 1.10.1（见 VALIDATION.md）。不要为了一个问题升级全部库；改一个依赖就重跑测试和 2 步短跑。

## 2 模型下载与锁定（已完成）

```sh
python scripts/prepare_model.py --config configs/cpu-long.json
```

脚本读取配置的 `model_id`，解析当前仓库 SHA，只下载该 SHA 的配置、tokenizer、safetensors 到 `models/cache/`，把 ID、SHA、本地路径写进配置里 `model_lock` 指向的文件。已有 lock 不覆盖。训练、B0、B1 都读同一个 lock；适配器目录里也会保存一份，加载时核对，防止把适配器套到别的模型版本上。这是唯一需要联网的步骤。

## 3 配置文件

真实数据从 `configs/cpu-long.json` 开始。每个实验复制一份到 `configs/local/E00X.json`（已被 git 忽略），只改本轮要改的那一项；不要直接改模板。

| 字段 | 当前值 | 含义 | 什么时候改 |
| --- | --- | --- | --- |
| `model_id`、`model_lock` | Qwen2.5-Coder-0.5B-Instruct、`models/model-lock.json` | 基础模型及其锁定文件 | 换模型（第 9 节） |
| `data` | `["data/private/train/B002.jsonl"]` | 训练池：一个或多个批次文件，只用 split=train 的行 | 每次增删批次 |
| `exclude_manifests` | `[]` | 训练前检查这些冻结基准的分组、gold、身份没有混进训练池 | 冻结基准 v0.1 后填 `["data/private/benchmark/suites/v0.1/manifest.json"]`；发布新版本时改为新版本。**文件必须存在** |
| `max_length` | 8192 | 单条样本（提示 + 答案）最大 token 数，超过即失败，不截断 | 按 `audit_data.py --tokens` 的最大值设置 |
| `max_steps` | 30 | 优化器更新次数，决定训练量 | 按目标 epoch 计算（第 8 节） |
| `learning_rate` | 1e-4 | 学习率；调度为 Trainer 默认的线性衰减到 0，无 warmup | 第 8 节 |
| `gradient_accumulation_steps` | 1 | 每步累积几条样本（batch 固定为 1） | 想让更新更平滑时设 4–8，同时按比例减少 `max_steps` |
| `lora_r`、`lora_alpha` | 8、16 | 适配器容量与缩放，惯例 alpha = 2r | 第 8 节 |
| `target_modules` | `["q_proj","v_proj"]` | 加适配器的层 | 第 8、9 节 |
| `attn_implementation` | `sdpa` | 注意力实现 | 一般不改 |
| `gradient_checkpointing` | true | 用重算换内存；长序列必须开（关掉会 OOM） | 一般不改 |
| `threads` | 8 | CPU 线程数 | 先单独做一次线程对比（8/16/32） |
| `seed` | 42 | 随机种子 | 估计波动时同配置换种子重跑 |
| `generation` | `{}` | 透传给 `model.generate` 的额外参数，如 `{"repetition_penalty": 1.05}` | 改了就必须重跑 B0，因为 B0、B1 生成设置必须一致 |

固定在代码里、目前不能通过配置改的：batch=1、FP32、`lora_dropout=0`、无 warmup、不保存中间 checkpoint、贪心解码（`do_sample=False`）。确实需要时改 `scripts/train.py` 或 `scripts/generate.py`，并作为单独一轮实验。

提示词的拼法在 `scripts/common.py` 的 `messages()`：固定的 system 指令 + 五段输入按"业务规则 / 测试剧本 / 可用 API / 框架约定 / 参考脚本"顺序拼接。训练和推理共用这一个函数。改它等于改了任务定义：需要重新训练，基准也要发布新版本，新旧结果不能比较。system 指令目前写的是 unittest，你的框架基类不同也没关系（框架约定在 `framework` 段里），但如果要改指令措辞，按"改任务定义"处理。

## 4 训练前检查

```sh
python scripts/audit_data.py data/private/train/*.jsonl --out runs/audit/E001.json \
  --tokens --config configs/local/E001.json \
  --exclude-manifest data/private/benchmark/suites/v0.1/manifest.json
```

看报告中的：样本数、source_group 数、origin 分布、token 长度最大值与超长样本、基准排除问题。超长样本先判断资料是否多余（例如参考脚本放了三份），不要为了通过检查删掉关键规则。

## 5 训练

```sh
python scripts/train.py --config configs/local/E001.json --run runs/train/E001-check --max-steps 2   # 先短跑
nohup python scripts/train.py --config configs/local/E001.json --run runs/train/E001 > runs/train/E001.log 2>&1 &
tail -c 300 runs/train/E001.log | tr '\r' '\n' | tail -2
```

运行目录已存在会拒绝启动，失败后换新目录。产物：

| 文件 | 看什么 |
| --- | --- |
| `status.json` | `training_completed`；`steps`；`train_samples`；`epochs`；`adapter_max_abs_change` 必须大于 0；`quality_verdict` 保持 `not_evaluated` 是正确的 |
| `metrics.jsonl` | 每步 `loss`、`grad_norm`、`learning_rate`、`elapsed_seconds` |
| `data-manifest.json` | 训练池各文件和排除清单的 SHA256 |
| `token-lengths.json`、`parameters.json` | 样本长度、可训练参数量 |
| `config.json`、`environment.json`、`model-lock.json` | 复现所需 |
| `adapter/` | 适配器权重和 tokenizer |
| `error.txt` | 失败时的完整异常 |

强制杀进程可能来不及写 `failed`，此时 `started` 不代表还在运行，记为 interrupted 并确认进程状态。没有断点续训，失败后从基础模型重新开始。

## 6 读训练结果：loss 只是第一道关

1. 看 `metrics.jsonl` 的 loss 曲线：应先下降后趋缓。
2. 看 `status.json` 的 `epochs`：样本少时很容易不知不觉训了十几个 epoch。
3. 训练本身没有验证集 loss；效果只看基准 dev 上的 B1 对 B0（[03-evaluation.md](03-evaluation.md)）。
4. 想比较不同训练量（例如 1/2/3 epoch），目前要分别训练（不同 `max_steps`），各算一组 B1。

## 7 调用模型的代码

### 7.1 命令行

| 用途 | 命令 |
| --- | --- |
| 在基准上批量生成（正式评测） | `python scripts/bench/run_generate.py --suite <suite> --config <cfg> [--adapter runs/train/E001] --splits dev --experiment E001 --arm B1` |
| 对训练格式 JSONL 快速看几条（调试） | `python scripts/generate.py --config <cfg> [--adapter runs/train/E001] --split dev --max-new-tokens 1024 --out runs/tmp/look` |

`--adapter` 传训练运行目录（`runs/train/E001`），不是它下面的 `adapter/`。不传 `--adapter` 就是未训练模型（B0）。两条命令共用 `generate.generate_items()`，保证设置一致；都不会执行生成出来的代码。输出里 `records.json` 的 `hit_token_limit` 为 true 表示被截断。

### 7.2 在 Python 中调用（复用工程代码）

```python
import sys, torch
sys.path.insert(0, "scripts")
from common import read, messages
from generate import load_model

config = read("configs/local/E001.json")
tokenizer, model, lock = load_model(config, "runs/train/E001")   # 第二个参数传 None 即 B0

task = {"id": "demo", "inputs": {"rules": "...", "scenario": "...", "api": "...",
                                 "framework": "...", "reference": "无参考"}}
ids = tokenizer.apply_chat_template(messages(task), tokenize=True, add_generation_prompt=True,
                                    return_tensors="pt")
with torch.inference_mode():
    out = model.generate(ids, attention_mask=torch.ones_like(ids), do_sample=False,
                         max_new_tokens=2048, pad_token_id=tokenizer.eos_token_id)
print(tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True))
```

### 7.3 不依赖工程代码（例如给别的服务集成）

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base = "<models/model-lock.json 里的 local_path>"
tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float32, local_files_only=True)
model = PeftModel.from_pretrained(model, "runs/train/E001/adapter").eval()
# 提示词必须与 scripts/common.py 的 messages() 完全一致，否则等于换了任务
```

需要单一权重文件（部署到其他推理框架）时可以合并：`merged = model.merge_and_unload(); merged.save_pretrained("runs/merged/E001"); tokenizer.save_pretrained("runs/merged/E001")`。合并产物是新制品，记录来源适配器和基础模型 SHA；不要拿它与未合并的结果混在一个对比里而不说明。vLLM 等推理框架也可直接加载 LoRA 适配器而不合并。

## 8 根据结果调参

### 8.1 调整顺序

1. **先排除数据和输入问题**。大多数退步来自数据：target 用了输入里没有的接口、参考脚本与答案太像、标签错误、正常流/异常流比例严重失衡。改数据比改超参数有效得多。
2. **再调训练量**（epoch，即 `max_steps`）。
3. **再调学习率**。
4. **最后调 LoRA 容量**（`lora_r`、`target_modules`）。
5. 生成设置（`max_new_tokens`、`generation`）单独一轮，并且 B0 同步重跑。

每轮只改一项，用新的实验编号。`max_steps` 的计算：

```text
max_steps = 训练样本数 × 目标 epoch ÷ gradient_accumulation_steps
例：120 条 × 3 epoch ÷ 1 = 360 步 ≈ 360 × 83 秒 ≈ 8.3 小时（本机 5k–7k token 实测均值）
```

### 8.2 起点与常见范围

| 参数 | 起点 | 常见尝试 | 备注 |
| --- | --- | --- | --- |
| epoch | 2–3 | 1 / 2 / 3 / 5 | 几十条样本时也不要超过 5；看 dev 是否开始退步 |
| `learning_rate` | 1e-4 | 5e-5 / 1e-4 / 2e-4 | LoRA 通常比全参数微调高一个数量级 |
| `lora_r` / `lora_alpha` | 8 / 16 | 16 / 32 | 数据少时加容量意义不大 |
| `target_modules` | q_proj, v_proj | 全部线性层：q/k/v/o_proj、gate/up/down_proj | 代码任务常见做法；训练参数量和耗时会增加 |
| `gradient_accumulation_steps` | 1 | 4、8 | 等效 batch 变大、更新更稳；`max_steps` 按比例缩小 |
| `seed` | 42 | 43、44 | B1 与 B0 只差一两个任务时，换种子确认是否只是波动 |

### 8.3 诊断表

先用 `compare.py` 的报告定位"在哪一层、哪类任务上变了"，再对照下表。

| 现象（在哪看） | 可能原因 | 下一轮只改 |
| --- | --- | --- |
| loss 几乎不降（`metrics.jsonl`） | 学习率太小、步数太少 | 学习率 ×2，或增加步数 |
| loss 抖动大或上升 | 学习率太大；batch=1 噪声大 | 学习率减半，或梯度累积 4 |
| loss 很快接近 0，dev 上 B1 退步 | 过拟合：epoch 太多、样本少或近重复多 | 减少 epoch；补充不同 source_group 的数据 |
| B1 与 B0 几乎完全相同，`adapter_max_abs_change` 很小 | 训练量不足 | 增加步数或学习率；扩大 `target_modules` |
| L0/L1 变好（无围栏、骨架正确），L2.5 不变 | 学到了格式，没学到剧本 → 断言的对应关系 | 正常的早期现象；增加数据量和场景覆盖，检查 oracle 失败原因 |
| `ungrounded_calls` 增加（编造接口） | 训练 target 里有输入找不到依据的调用，模型学会了"凭记忆写" | 修数据：补全 `api` 或剔除这些样本 |
| `copied_identity` 增加（照抄参考脚本） | 参考脚本与 target 太像 | 修数据：换参考或去掉近重复参考 |
| 异常流（`flow=exception` 切片）退步，正常流不变 | 训练池异常流样本少，或异常流 target 断言写得弱 | 补异常流样本；审核其断言 |
| 某个 domain 退步 | 该领域训练样本少或与其他领域约定冲突 | 补该领域数据 |
| `hit_token_limit` 增加 | 输出变长或复读 | 先看原始输出；复读试 `repetition_penalty`，需要更长输出就加 `max_new_tokens`，两者都要 B0 同步 |
| 训练 OOM 被杀 | 序列长、未开梯度检查点 | `gradient_checkpointing: true`；精简输入 |
| 训练太慢 | 线程数未调 | 线程对比实验（8/16/32），不同时改其他参数 |

## 9 换模型

比较不同开源模型时，**训练池和基准版本保持不变**，每个模型各有自己的 B0 和 B1。能说的结论是"模型 X 训练后（B1-X）比模型 Y 训练后（B1-Y）在基准 v0.1 dev 上好"，以及"训练对 X 的提升（B1-X 对 B0-X）"。

1. 新建配置 `configs/local/<模型简称>-base.json`：改 `model_id`，`model_lock` 改为新文件（如 `models/model-lock-qwen1.5b.json`），不要覆盖现有 lock。
2. `python scripts/prepare_model.py --config configs/local/<模型简称>-base.json`。
3. 查线性层名称，决定 `target_modules`：

   ```python
   import torch; from transformers import AutoModelForCausalLM
   m = AutoModelForCausalLM.from_pretrained("<local_path>", torch_dtype=torch.float32)
   print(sorted({n.split(".")[-1] for n, x in m.named_modules() if isinstance(x, torch.nn.Linear)}))
   ```

   Qwen、Llama、Mistral、DeepSeek-Coder 一类通常是 q/k/v/o_proj 和 gate/up/down_proj；其他架构名称不同（如 `qkv_proj`、`query_key_value`）。
4. 用新 tokenizer 重跑 `audit_data.py --tokens`：不同 tokenizer 的 token 数不同，`max_length` 要按新结果设置，并确认不超过模型上下文长度。
5. 2 步短跑。`common.encode_sample` 会检查聊天模板的前缀一致性；报 `chat template prefix mismatch`，或模型不支持 system 角色，说明该模型的模板与当前提示词拼法不兼容，需要单独处理（改 `messages()` 等于改任务，见第 3 节）。
6. 估算资源：FP32 下仅权重约 4 字节/参数（1.5B ≈ 6 GB、3B ≈ 12 GB、7B ≈ 28 GB），训练另有梯度、优化器状态（只针对 LoRA 参数，很小）和激活。0.5B 在 5k–7k token、梯度检查点下峰值 22.5 GB；容器上限 64 GB。1.5B 预计可行，3B 需实测，7B 在 FP32 + 8k 序列下大概率超限。耗时大致随参数量线性增长。以 2 步短跑的实测为准。
7. 跑该模型的 B0、训练、B1，再用 `compare.py` 把多个模型的运行目录放在一起对比。

## 10 常见问题

| 现象 | 先检查 | 记录什么 |
| --- | --- | --- |
| 导入失败 | 是否在 `.venv`、依赖组合 | 完整异常、`pip freeze` |
| `model lock mismatch` | 配置的 `model_id` 与 lock 不一致 | 两者的值 |
| `adapter and baseline model revisions differ` | 适配器来自另一个模型版本 | 两个 lock |
| 训练报某个 manifest 不存在 | `exclude_manifests` 指向尚未冻结的版本 | 改为已冻结版本 |
| 训练报 source_group reserved / identical gold | 训练池混入了基准实例 | 从训练池删除该样本，新建批次文件 |
| 超长样本失败 | 资料是否多余，还是任务本来就需要长上下文 | 原长度与处理决定，不静默删除 |
| `adapter weights did not change` | `target_modules` 名称、labels 是否全为 -100 | `parameters.json`、`token-lengths.json` |
| loss 下降但输出仍差 | 见第 8 节 | 原始输出与错误分类 |
