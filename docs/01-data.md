# 准备训练数据

本页回答三个问题：一条训练样本是什么、文件放哪里、每批数据要做哪几步。基准实例的审核与判定标准见 [05-benchmark.md](05-benchmark.md)。

## 1 任务边界

一条样本 = 五段输入资料 → 一份完整 Python 测试文件。

| 输入字段 | 内容 | 来源 |
| --- | --- | --- |
| `rules` | 业务规则原文或足以判断本场景的片段 | 需求 / 规则文档 |
| `scenario` | 测试剧本：前置、动作、预期（正常流或异常流） | 已确认的剧本 |
| `api` | 用到的函数签名、参数含义、错误与副作用 | API 封装仓库 |
| `framework` | 导入、基类、生命周期、断言、清理、执行入口 | 框架仓库，`data/private/build/context/framework.md` |
| `reference` | 相关参考脚本；确实没有时写"无参考" | 存量脚本，排除目标脚本本身及其近重复 |

训练教的是"给定剧本和资料时，怎样忠实地写成符合团队约定的脚本"，不是让模型记住业务规则，也不是让它设计用例。测什么、预期是什么，由人写在 `scenario` 里；业务知识必须出现在输入里：上线后模型面对的是新需求，靠训练记忆猜规则只会产生编造。第一轮不同时训练需求分析、剧本设计、工具检索和多轮修复。

### 1.1 收录范围

| 收录 | 排除 |
| --- | --- |
| 有明确剧本（前置、动作、预期写清楚）的纯接口业务流脚本，正常流和异常流都收 | 系统类测试：限流、性能、压测、稳定性、容灾、监控告警 |
| 规则文档写明的业务配额（如"每用户每日最多 N 笔"）——它是业务规则 | 需要操作手机界面或 OCR 的脚本（`USE_AT = True`） |
| | 没有明确剧本、只有"应该返回错误"这类笼统描述的脚本 |

训练数据和基准使用同一个范围：只排除一边会出现"考没教过的"或"教了不考的"。范围写在数据构建提示词第 1 节，盘点阶段就把范围外的脚本标出来。

`scenario` 里必须写明预期：正常流写成功码和应观察到的副作用，异常流写契约约定的错误码和文案。脚本断言了而剧本没写的预期，要补进剧本——否则模型无从得知，基准的判定标准也没有依据。

资料缺失（规则找不到出处、接口签名不明）的样本不进入本任务的训练集，记在 `build_notes.gaps`，留待补齐。

## 2 目录：什么放在哪里

`data/private/` 已被 git 忽略，以下内容都不进公开仓库。

```text
data/private/
  build/                      数据制造（可反复修改）
    prompt-B001.md            每批一份：由 templates/data-build-prompt.md 填写而来
    context/framework.md      框架约定文本（各批共享，更新时注明日期）
    context/inventory-B001.md 存量盘点结果
    tools/                    构建脚本：inventory / select_candidates / spec_<批次> / build_samples
  candidates/                 AI 构建、尚未审核的样本（review_status=pending）
    candidates-B002.jsonl
    candidates-B002-checks.md 构建脚本的自检报告
  train/                      训练池：只放审核通过、split=train 的样本，按批次一个文件
    B001.jsonl  B002.jsonl ...
  benchmark/                  基准资产（见 05-benchmark.md）
    rules/ taxonomy.json rubric.md pool/ suites/
```

规则：

1. `candidates/` 是草稿区，训练和评测都不直接读它。
2. `train/` 的文件一旦被某个实验用过就不再修改；要改就生成新批次文件（如 `B002-fix.jsonl`）并在新实验里替换。实验的 `data-manifest.json` 记录了每个文件的 SHA256，修改旧文件会让旧实验无法复现。
3. 一条样本只能去一处：训练池或基准，不能两边都有。按 `source_group` 分流，同一组整体去同一处。

## 3 每批数据的流程

| 步骤 | 谁做 | 做什么 | 产物 |
| --- | --- | --- | --- |
| 1 盘点 | AI + 你确认 | 列出可用的测试脚本、领域、API、框架入口 | `build/context/inventory-B002.md` |
| 2 填提示词 | 你 | 复制 `templates/data-build-prompt.md` → `build/prompt-B002.md`，填第 1 节（仓库路径、批次号、范围、数量） | 提示词 |
| 3 构建 | AI | 按提示词分阶段执行，每个停止点等你确认 | `candidates/candidates-B002.jsonl`、自检报告 |
| 4 审核 | 你 | 逐条看业务含义（第 5 节清单），改 `review_status`、`tags`，处理 `gaps` | 审核后的候选文件 |
| 5 分流 | 你 | 训练样本 → `select_rows.py`；基准样本 → `import_pool.py` | `train/B002.jsonl`、`benchmark/pool/<id>/` |
| 6 门禁 | 程序 | 字段、分组、重复、语法、真实 token 长度、基准排除 | `runs/audit/E00X.json` |

B001 的构建工具保留在 `build/tools/`，在 `data/private/build/` 下运行 `python3 tools/build_samples.py` 可重新生成 `candidates-B001.jsonl`（需要三个存量仓库可读）。新批次复制 `spec_B001.py` 为 `spec_B002.py`，改批次号和选样范围。

命令（工程根目录，已激活 `.venv`）：

```sh
# 5 分流：除了留给基准的两条，其余审核通过的 train 样本进入训练池
python scripts/select_rows.py --from data/private/candidates/candidates-B002.jsonl \
  --exclude-ids B002-009 B002-010 --out data/private/train/B002.jsonl
python scripts/bench/import_pool.py --from data/private/candidates/candidates-B002.jsonl --ids B002-009 B002-010

# 6 门禁：训练池全部批次 + 当前基准
python scripts/audit_data.py data/private/train/*.jsonl --out runs/audit/E001.json \
  --tokens --config configs/local/E001.json \
  --exclude-manifest data/private/benchmark/suites/v0.1/manifest.json
```

`select_rows.py` 只接受 `review_status=approved` 的行，拒绝覆盖已有文件，写出后会用训练时同一套校验重新读一遍。`audit_data.py --tokens` 用真实 tokenizer 和聊天模板统计每条样本长度，列出超过配置 `max_length` 的样本——训练遇到超长样本会直接失败，不会静默截断。

## 4 样本格式

JSONL 每行一个对象，参考 `data/public/toy.jsonl`。输入正文必须是实际文本，不能只写文件路径（模型看不到你的磁盘）。

```json
{
  "id": "B002-003",
  "source_group": "<领域>-<业务操作或脚本家族>",
  "split": "train",
  "origin": "reconstructed",
  "review_status": "approved",
  "provenance": ["<仓库>@<commit>:<脚本路径>", "<规则文档>@<版本>#<章节>"],
  "tags": {"flow": "exception", "domain": "<领域>", "scenario_type": "limit"},
  "inputs": {"rules": "...", "scenario": "...", "api": "...", "framework": "...", "reference": "..."},
  "target": "<完整、审核过的 Python 测试文件>",
  "build_notes": {"rules_basis": "...", "gaps": [], "redactions": [], "split_reason": "...",
                  "near_duplicates": [], "estimated_tokens": 5200}
}
```

| 字段 | 训练时是否使用 | 说明 |
| --- | --- | --- |
| `id`、`source_group`、`split`、`origin`、`review_status`、`provenance`、`inputs`、`target` | 校验必需 | 缺任何一个，训练拒绝启动 |
| `inputs` | 拼成提示词 | 拼接方式在 `scripts/common.py` 的 `messages()`，训练和推理共用 |
| `target` | 监督目标 | 只有这部分计算 loss（输入部分 labels=-100） |
| `tags` | 不参与训练 | 用于统计训练池构成，与基准的 taxonomy 取值一致，便于对照 |
| `build_notes` | 不参与训练 | 仅供审核 |

`origin`：`original` 是当时实际保存的输入；`reconstructed` 是根据历史资料重建（目前大多数属于此类）；`synthetic` 是独立编写的教学数据。不能用 synthetic 掩盖公司资料的改写来源。

## 5 审核清单

先读规则和剧本，再看脚本。脚本不是业务规则的唯一证据。

- 剧本是否写明了预期，脚本的断言是否与剧本一致：脚本断言了剧本没写的预期，补进剧本；剧本写了而脚本没断言的，说明这个脚本不适合做训练答案。
- 正常流：除了成功码，是否断言了剧本写明的副作用（状态、余额、记录）。
- 异常流：前置是否只违反目标规则这一条，请求是否真的到达目标分支，而不是先被另一条校验拒绝；断言是否包含约定的错误码和关键文案，而不只是"失败"。
- 是否属于范围内的业务流脚本（1.1 节）。
- SDK 是否会自动修正原本想发送的非法值。
- 前置、资源标识和清理能否重复执行。
- 脚本用到的每个接口、参数、常量，是否都能在 `inputs` 中找到依据。人工补过的隐藏参数，先找到契约来源并补进 `api`。
- 参考脚本是否和目标脚本几乎一样（会让模型学会照抄，整理前的试验中观察到过复制参考脚本 `script_id` 的现象）。

无法确认的样本保持 `pending`，不导出。当前环境无法执行的记为 execution_blocked，不当作脚本错误，也不标为执行通过。

## 6 分组、分流与去重

- `source_group`：同一需求来源、同一业务操作或同一脚本家族用同一个值。同一模板只改参数、同一需求的改写，必须同组。
- **先定基准、再定训练池。** 基准实例占用的 `source_group` 整组都不能进训练池。如果先把训练池凑满再挑基准，挑中的家族就得从训练池里删掉。做法：盘点后先选出 12–16 个打算做基准的家族（每个家族 1 条），其余家族才进入训练数据构建。
- 基准优先挑这类样本：独立分组、规则来源清楚、剧本写明了具体预期（错误码、文案、副作用），并且正常流和异常流都有、覆盖多个领域。
- 训练池里同一家族可以有多条（同组即可），但每个家族设上限（构建提示词默认 3 条），避免训练偏向某个模板。
- 程序能检查：同组跨 split、完全相同的 target、基准分组或 gold 混入训练池、`script_id` 身份重复（`audit_data.py --exclude-manifest`、`check_leakage.py`）。近重复只能给出提示，需要人工判断。

## 7 需要多少数据

几十、几百、几千条不是同一个量级，能期待的效果不同：

| 规模 | 通常能学到 | 不能期待 |
| --- | --- | --- |
| 几十条 | 输出格式（无围栏、完整文件）、框架骨架、命名与断言风格 | 稳定的业务正确性；结论容易被单条样本左右 |
| 几百条 | 框架约定、常见场景的前置/清理套路、按剧本区分正常流和异常流的断言写法 | 覆盖不到的领域和新接口 |
| 几千条 | 跨领域的稳定性、较少的编造与漏清理 | 输入里没有的业务知识 |

比"多少条"更重要的是：覆盖多少个 `source_group`、领域，正常流与异常流是否都有，审核质量如何。100 条来自 5 个脚本家族的近似样本，不如 50 条来自 30 个家族的样本。

建议用学习曲线代替拍脑袋：训练池积累到一定规模后，分别取 25%、50%、100%（按 source_group 抽，不按行抽）各训练一次，在同一个基准 dev 上对比。曲线还在上升就继续积累数据；已经平了就该改数据质量、输入构造或模型，而不是再堆数量。

### 7.1 第一批 60 条从哪里来

B001 盘点的领域目录 `usecase-2982374344089851` 共 70 个脚本：去掉需要界面操作的 23 个、没有明确剧本的 16 个，剩 31 个；按近重复家族合并后只有 14 个家族（见 `data/private/build/context/inventory-B001.md`）。这个目录不够 60 条，也不够同时给基准留出 12–16 个家族。需要：

1. 扩展到更多领域目录（盘点时一次列出多个目录）。
2. 训练池允许同一家族多条（每族上限 3），近重复家族就不必只留 1 条。
3. 对"没有明确剧本"的脚本，如果你能补写剧本，补写后可以收录（`origin` 仍为 `reconstructed`，在 `build_notes` 说明剧本由人补写）。

60 条是"几十条"量级：预期主要改善格式、骨架和约定，B1 对 B0 的业务正确性差异可能不明显。它的价值在于跑通一次完整的训练—评测循环，并作为学习曲线的第一个点。

## 8 同时开始记录新任务

从下一次用现有工作流（A）写脚本开始，保存：输入快照、工作流与 Skill 版本、初次输出、人工修改、最终代码和执行结果。这些是将来最好的 `original` 样本和 `fresh` 基准实例，也是计算"人工修复时间"的唯一来源。不要只保存最后成功的文件。
