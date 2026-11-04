# ai-test-posttraining：测试脚本生成的后训练与评测框架

**版本 v0.1（2026-11-01）**。用审核过的"测试剧本 + 契约 + 框架约定 → 测试脚本"样本，对开源代码模型做 SFT（LoRA）；再在独立、冻结的基准上，与未训练模型（B0）和现有工作流（A）对照，判断训练能否减少生成错误、提示长度和人工修改成本。

## 任务定义

模型的职责是**根据人工编写的测试剧本，忠实地写出测试脚本**：

- 前提：被测接口和测试脚本都按契约实现，契约规定输入、输出和业务规则。
- 测什么、预期是什么，由人在剧本中决定（正常流、异常流）。模型不设计用例，不补充剧本以外的测试。
- 范围是业务流（契约、业务规则）。系统类测试（限流、性能、稳定性、容灾）不在范围内，训练数据和基准都不收。
- 因此评测只问一件事：生成的脚本是否按剧本构造前置、调用接口、断言剧本写明的预期、完成清理，并且能在正确环境中跑通。

## 当前状态

框架、标准和工具已就绪，**基准内容与规则待你 review**，尚未冻结任何基准版本，训练池为空，没有任何效果结论。环境、模型、训练与生成流程已在目标 CPU 服务器上验证过（[VALIDATION.md](VALIDATION.md)）。

## 版本

| 对象 | 当前版本 | 位置 | 何时递增 |
| --- | --- | --- | --- |
| 框架（代码、文档、模板） | v0.1 | 本页 | 设计或标准变动 → v0.2…；你确认可用于正式训练评测 → v1.0 |
| 全局框架规则 | v0.1 | `data/private/benchmark/rules/framework-v0.1.json`（公开示例 `configs/bench/rules.toy.json`） | 修改时复制为新文件 `framework-v0.2.json`，旧文件不动 |
| 标签体系 | v0.1 | `data/private/benchmark/taxonomy.json` 的 `name` | 修改时改 `name` |
| 人工评审标准 | v0.1 | `data/private/benchmark/rubric.md`（模板 `templates/bench-rubric.md`） | 修改时写修订记录 |
| 评分器 | 0.1 | `scripts/bench/benchlib.py` 的 `SCORER_VERSION` | 判定逻辑变化时递增，旧运行重新打分 |
| 基准 | 未冻结；第一个冻结版本为 v0.1 | `data/private/benchmark/suites/v0.1/` | 任何修改 → v0.2…；规模达到 60–100 个实例且你认可 → v1.0 |
| 实验编号 | 从 E001 开始 | `runs/records/E001.md` | 每轮一个 |
| 数据批次 | B001 为 10 条试做（候选已删，构建工具保留）；下一批 B002 | `data/private/train/B002.jsonl` | 每批一个 |

## 从这里开始

| 你要做的事 | 读这个 |
| --- | --- |
| 每一轮要做什么（清单） | [docs/00-runbook.md](docs/00-runbook.md) |
| 准备训练数据、放到哪里 | [docs/01-data.md](docs/01-data.md) |
| 训练、调参、换模型、调用模型 | [docs/02-training.md](docs/02-training.md) |
| 对照组与结果判读 | [docs/03-evaluation.md](docs/03-evaluation.md) |
| 记录实验与发布 | [docs/04-recording.md](docs/04-recording.md) |
| 建设与使用基准 | [docs/05-benchmark.md](docs/05-benchmark.md) |
| 基准的设计依据（review 用） | [docs/06-benchmark-design.md](docs/06-benchmark-design.md) |

## 整体流程

```text
存量仓库（框架 / API 封装 / 测试脚本）
   │  templates/data-build-prompt.md + data/private/build/tools/
   ▼
data/private/candidates/   AI 构建的待审样本（pending）
   │  人工审核，决定每个 source_group 的去向（只能去一处）
   ├───────────────────────────────┐
   ▼                               ▼
data/private/train/            data/private/benchmark/pool/
训练池（approved）              基准候选实例 + 判定标准 oracle.json
   │                               │  build_suite.py 冻结
   │                               ▼
   │                        data/private/benchmark/suites/vX/（只读）
   │   check_leakage.py：训练池与基准不得重叠
   ▼                               │
train.py → runs/train/EXXX/        │
   │ 适配器                         │
   ▼                               ▼
bench/run_generate.py（B0 未训练、B1 训练后，同一设置；A 用 import_run.py 导入）
   ▼
bench/score.py（L0–L2.5 自动） + review.csv（L3 执行、L4 人工评审）
   ▼
bench/compare.py → 实验记录 runs/records/EXXX.md → 决定下一轮只改什么
```

评测分层：L0 形式、L1 框架约定、L2 依据（不编造、不照抄）、L2.5 是否实现剧本（实例判定标准）、L3 在正确环境中跑通、L4 人工评审。没有故障版本（mutation）这一层：剧本是否充分由写剧本的人负责，不属于模型的评测范围。

## 目录

```text
configs/
  cpu-smoke.json             toy 连通配置（短序列）
  cpu-long.json              真实数据配置模板（长序列：sdpa + 梯度检查点，max_length 8192）
  bench/rules.toy.json       公开示例：全局静态规则
  bench/taxonomy.toy.json    公开示例：标签体系
  local/                     每个实验的配置副本（已忽略）
data/
  public/toy.jsonl           3 条虚构训练格式样本，仅用于连通
  public/bench-pool/         3 个虚构基准实例（正常流 2、异常流 1），实例格式示例
  private/                   内部数据，已被 git 忽略（结构见 docs/01-data.md）
examples/toy_api.py          虚构示例依赖的函数
scripts/
  common.py                  数据校验、提示词拼接、聊天模板编码、基准排除检查
  audit_data.py              训练池门禁（可选：真实 token 长度、基准排除）
  select_rows.py             审核通过的候选样本 → 训练池批次文件
  prepare_model.py           下载并锁定模型版本
  train.py                   CPU LoRA 训练
  generate.py                对训练格式数据快速生成（调试用）
  bench/                     基准工具：import_pool / build_suite / check_leakage /
                             run_generate / import_run / score / compare / benchlib
tests/                       数据门禁、标签掩码、基准评分器的回归测试
templates/                   数据构建提示词、实验、问题记录、评审标准、数据卡、模型卡、报告
docs/                        操作手册
models/  runs/               本机模型缓存与运行产物，已被 git 忽略
```

## 三种不同的结论

| 阶段 | 可以说什么 | 需要看到什么 |
| --- | --- | --- |
| 数据准备完成 | 有可追溯、审核过的输入输出 | 来源、审核结论、分组、门禁报告、防泄漏报告 |
| 训练流程跑通 | 完成了 LoRA 工程验证 | 参数变化、适配器保存并能重新加载生成 |
| 业务效果成立 | 在定义的任务范围内有某种改善 | 冻结基准上 B1 相对 B0（及 A）的逐任务对照，含执行与人工评审 |

loss 下降、静态指标改善都不等于第三种结论。

## 初始技术选择

- 小模型：`Qwen/Qwen2.5-Coder-0.5B-Instruct`，用于学习流程，不作为业务模型推荐；换模型方法见 docs/02-training.md。
- 方法：SFT + LoRA，Transformers Trainer + PEFT，直接构造 completion-only 标签。
- CPU：FP32；长序列启用梯度检查点。没有引入 BF16、QLoRA。

## 公开与内部

公开仓库可保存通用代码、虚构样本与实例、模板和经审阅的报告。真实业务数据、基准实例、原始日志、生成代码和权重保留在内部：`data/private/`、`models/`、`runs/`、`configs/local/` 已忽略。`.gitignore` 不保护已被 Git 跟踪的文件，也不构成发布授权。发布前为你拥有权利的代码、文档和数据明确许可；基础模型及第三方内容保持各自许可。

一手资料：[模型卡](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct)、[CPU 训练](https://huggingface.co/docs/transformers/main/cpu)、[Trainer 4.57.1](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/trainer)、[PEFT 入门](https://huggingface.co/docs/peft/v0.17.0/en/quicktour)、[TRL SFT](https://huggingface.co/docs/trl/sft_trainer)。
