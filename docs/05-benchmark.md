# 基准操作手册

设计依据见 [06-benchmark-design.md](06-benchmark-design.md)。本页讲怎么做：入池、写判定标准、补充私域规则和经验、冻结、防泄漏、执行与评审，以及生成与打分。

## 1 基准评什么

基准只回答一个问题：**模型生成的脚本是否忠实实现了测试剧本**。也就是在契约和框架约定之下，是否按剧本构造前置、调用剧本要求的接口、断言剧本写明的预期、完成清理，并且能在正确环境中跑通。

剧本本身是否充分、能否发现系统缺陷，由写剧本的人负责，不在基准评测范围内。所以基准不做故障版本（mutation testing）。系统类测试（限流、性能等）不在任务范围内，不收作实例。

基准 = 固定的实例集 + 每个实例的判定标准 + 固定的全局规则 + 固定的评分器，整体带版本、只读。A / B0 / B1、不同实验、不同模型都在同一个版本上打分，结果才能比较。

```text
data/private/benchmark/
  README.md                 负责人、版本历史、v0.1 review 清单
  rules/framework-v0.1.json 全局静态规则：框架约定中可机检的部分
  taxonomy.json             标签体系与允许的 split
  rubric.md                 人工评审标准（由 templates/bench-rubric.md 复制并补充）
  pool/<instance_id>/       审核中的实例，可以修改
  suites/vX/                冻结版本，只读
    manifest.json rules.json taxonomy.json instances/<instance_id>/
  suites/leakage-vX.json    防泄漏报告
```

公开示例：`configs/bench/rules.toy.json`、`configs/bench/taxonomy.toy.json`、`data/public/bench-pool/`（正常流 2 个、异常流 1 个）。

## 2 实例格式

```text
pool/<instance_id>/
  task.json         模型能看到的输入 + 标签
  gold.py           审核过的标准答案（不给模型；用于校准和参考相似度）
  oracle.json       本实例的判定标准（从剧本写出）
  provenance.json   来源与审核
```

`task.json`（`instance_id` 必须等于目录名）：

```json
{
  "instance_id": "B002-061",
  "split": "dev",
  "source_group": "<领域>-<业务操作>",
  "tags": {"flow": "exception", "domain": "<领域>", "scenario_type": "limit", "difficulty": "medium"},
  "inputs": {"rules": "...", "scenario": "...", "api": "...", "framework": "...", "reference": "..."}
}
```

`inputs` 的五段与训练样本完全同构，经过同一个 `messages()` 拼成提示词。`scenario` 必须写明预期（第 4 节的判定标准都从这里来）。`reference` 只能取自训练池或存量脚本，不能是其他基准实例的 gold。

`provenance.json`：`origin`、`sources`（仓库@commit、规则文档@版本）、`review_status`（pending / approved）、`reviewer`、`reviewed_at`、`review_notes`。

## 3 入池与审核

```sh
python scripts/bench/import_pool.py --from data/private/candidates/candidates-B002.jsonl --ids B002-061 B002-062
```

导入时会根据 gold 预填一份 `status: "draft"` 的 oracle，`provenance.review_status` 为 pending。预填只是为了少打字：它从答案的写法反推，可能把偶然的测试数据当成预期，也可能多收了只是前置用到的接口。审核时**只对照 `scenario` 和 `rules`** 逐项删改（第 4 节），然后把 `oracle.status` 改为 `approved`、`provenance.review_status` 改为 `approved` 并填 `reviewer`、`reviewed_at`。

出题和审核是同一人时，写 gold 和审核 oracle 最好隔开一段时间；审核时先只读 `scenario`，列出"应该断言什么"，再对照 oracle。这一点作为已知限制写进 `benchmark/README.md` 的版本说明。

导入基准的样本不能再进入训练池；同一 `source_group` 的其他样本也一样。

检查 pool 状态（不写文件，review 期间随时可以运行）：

```sh
python scripts/bench/build_suite.py --version v0.1 --check
```

## 4 编写 oracle.json

```json
{
  "status": "approved",
  "target_branch": "单笔金额超过上限被拒绝（异常流）",
  "evidence": "scenario",
  "must_call": ["<接口类>.<方法>"],
  "expect": [
    {"kind": "assert_value",    "target": "retcode", "value": 1001},
    {"kind": "assert_contains", "target": "retmsg",  "value": "超过单笔限额"}
  ],
  "cleanup_required": ["<清理接口>"],
  "must_not_call": [],
  "notes": "剧本前置：余额充足、未触发日限额，只违反单笔上限这一条"
}
```

原则：**oracle 是剧本的机器可检查版本。** 剧本写了的才写进来，剧本没写的不写。

| 字段 | 静态怎么判 | 写法要点 |
| --- | --- | --- |
| `target_branch` | 不判，给评审看 | 一句话复述剧本：测哪条规则的哪个分支 |
| `evidence` | 必须是 `scenario` 或 `rules` | 预期写在剧本里填 `scenario`；剧本引用了规则条目、预期取自规则原文填 `rules`。不能只来自 gold |
| `must_call` | 候选脚本必须调用这些名字（按最后一段匹配；自己重新定义同名函数不算） | 剧本"动作"里要求调用的接口；不写只是取账号、取配置等前置辅助接口。每个都必须出现在 `inputs` 里，否则冻结时报错 |
| `expect` | 某条断言的参数中包含该常量（`full`）；值对了但断言对象不含 `target` 记为 `value_only`，不算通过 | 剧本"预期"里写明的每一项 |
| `cleanup_required` | 这些接口出现在 tearDown（含它调用的一层 self 方法）中 | 剧本或框架约定要求的清理 |
| `must_not_call` | 候选脚本不得调用 | 剧本或约定明确禁止的接口 |

`expect` 的两种 `kind`：

- `assert_value`：断言参数中有一个**类型和值都相同**的常量。`1001` 和 `"1001"` 不同，按接口实际返回的类型写。
- `assert_contains`：断言参数中有一个字符串常量**包含** `value`。用于文案，写剧本规定的关键部分，不写整句（整句可能带变量）。
- `target`：断言参数源码中应出现的片段，例如 `retcode`、`retmsg`、`balance`、`exception`。用来区分"断言了正确的对象"和"同一个数字碰巧出现在别的断言里"。留空表示不检查对象。

### 4.1 正常流与异常流

| | 正常流（`flow: normal`） | 异常流（`flow: exception`） |
| --- | --- | --- |
| 剧本 | 前置满足所有规则，请求应成功 | 前置按剧本只违反目标规则这一条，请求应被拒绝 |
| `expect` 写什么 | 剧本写明的成功码和副作用（状态、余额、记录数） | 剧本写明的错误码和文案 |
| 静态判不了、靠 L3/L4 | 副作用的值是否正确 | 请求是否真的走到目标分支，而不是先被别的校验拒绝 |

异常流示例：`data/public/bench-pool/toy-quantity/`——剧本要求"抛出 ValueError，且错误消息包含 digits"，oracle 就断言消息包含 `digits`（`target: "exception"`），而不只是 `assertRaises`。

### 4.2 什么不写进 expect

- 剧本没写的预期，即使 gold 断言了。这种情况先回头看剧本是否漏写：漏写就补剧本（改 `task.json` 的 `scenario`），再写进 oracle。
- 测试数据里的任意值：随机订单号、时间戳、自己选的金额（除非剧本规定这个值，如"上限 + 1"）。
- 写不出确定值的预期（"返回列表非空"）：不写进 `expect`，在 `notes` 里说明，由 L3/L4 判断。

### 4.3 校准

冻结时每个实例的 gold 必须通过自己的全部判定（`auto_pass`），否则拒绝冻结并列出原因。gold 通不过，要么 oracle 写严了，要么 gold 本身没按剧本写，要么全局规则与团队实际写法不符。冻结后也可以单独看：

```sh
python scripts/bench/score.py --gold --suite data/private/benchmark/suites/v0.1 --out runs/bench/v0.1/gold
```

## 5 补充私域规则与经验

经验分三类，各放一处：

| 经验类型 | 放在哪里 | 谁用 |
| --- | --- | --- |
| 框架约定中能机检的部分 | `rules/framework-v0.1.json` | 评分器（L1、L2） |
| 每个实例要测什么 | 该实例的 `scenario` 和 `oracle.json` | 评分器（L2.5） |
| 判断经验、正反例、常见陷阱 | `rubric.md` | 人工评审（L4） |

另外，写给模型看的框架约定在 `data/private/build/context/framework.md`（进入每条样本的 `framework` 段）。它和 `framework-v0.1.json` 描述的是同一套约定，改一处要检查另一处。

### 5.1 全局规则 `rules/framework-v0.1.json`

字段（公开示例 `configs/bench/rules.toy.json`）：

| 字段 | 含义 |
| --- | --- |
| `name` | 规则集名称与版本，如 `company-uat-v0.1` |
| `base_class` | 测试类必须继承的基类名 |
| `required_class_attrs` | 测试类必须定义的类属性（如脚本编号） |
| `required_methods` | 必须实现的方法（如 setUp / 测试方法 / tearDown） |
| `test_method_count` | 测试方法数量 `{"min": 1, "max": 1}` |
| `required_imports` | 必须出现的导入 |
| `super_calls` | 哪些方法必须调用 `super()`，`any`（任意位置）或 `last`（最后一句） |
| `forbidden_calls` | 禁用调用，如 `print` |
| `assert_min_args` | 各断言方法最少参数数（用来要求带断言消息） |
| `require_assert_message` | 是否要求所有断言带消息 |
| `test_docstring_markers_any` | 测试方法文档字符串须含其中之一（如正常 / 异常标记） |
| `allowed_names` | 不在输入中出现、但允许调用的名字（框架基类方法、工具函数） |
| `soft_checks` | 只报告不判失败的检查项 |
| `identity_attrs` | 视为脚本身份的属性名；候选脚本照抄参考脚本的这些值判失败 |
| `forbid_reference_identity`、`forbid_ungrounded_calls` | 是否把"照抄参考身份""调用输入中不存在的名字"判为失败 |

冻结前（review 期间）可以直接改这个文件。冻结后要改：复制为 `framework-v0.2.json`、改 `name`，旧文件不动；新规则随新的基准版本生效。改完用 `build_suite.py --check` 看所有 gold 是否仍通过。

### 5.2 标签体系 `taxonomy.json`

`splits` 列出允许的 split；`dimensions` 每个维度有 `required` 和 `values`（空列表表示不限值，如 `domain`）。实例使用未登记的标签会被拒绝冻结——先改 taxonomy，再打标签。

### 5.3 评审标准 `rubric.md`

团队的判断经验写在这里：什么算 minor_fix / major_fix、各领域常见的前置陷阱、正反示例。每次修改在文末修订记录写日期，并说明影响哪些已有评审。

### 5.4 已知坏样本

评测中发现一种新的错误模式（例如照抄参考脚本 `script_id`），在 `tests/test_bench.py` 加一个用例：构造这种坏样本，断言评分器能判它失败。然后再改评分器，并递增 `benchlib.SCORER_VERSION`。

## 6 冻结、版本与防泄漏

```sh
python scripts/bench/build_suite.py --version v0.1 --note "首个试用版本：16 个实例，dev"
python scripts/bench/check_leakage.py --suite data/private/benchmark/suites/v0.1 --train data/private/train/*.jsonl
```

冻结写出的内容：每个实例的 `task.json`、`gold.py`、`oracle.json`、`provenance.json`，当时的 `rules.json`、`taxonomy.json`，以及 `manifest.json`。manifest 记录每个文件的 SHA256、冻结时间、说明、评分器版本、按 split 与标签的计数，以及训练排除清单（`source_groups`、`gold_digests`、`gold_identities`）。文件全部只读，已存在的版本不允许覆盖；之后所有工具读取 suite 时都会核对 SHA。

冻结前的检查：每个实例合法且 gold 校准通过、`source_group` 不跨 split、gold 无重复、身份不重复、`reference` 中不含其他实例的 gold。`--ids` 只冻结指定实例，`--only-ready` 跳过不合格实例。

`check_leakage.py`：

| 类别 | 内容 | 处理 |
| --- | --- | --- |
| 硬失败（退出码 1） | 基准分组出现在训练池；gold 与训练 target 相同；`script_id` 身份共享；gold 出现在训练样本的 `reference` 中（身份相同，或 gold 的片段指纹 ≥ 80% 包含在 reference 里，`--contain`） | 从训练池移除对应样本（新建批次文件） |
| 软提示（verdict=review） | 近重复：gold 与训练 target 的片段指纹 Jaccard ≥ 0.6（`--near`） | 人工判断，结论写进实验记录 |

训练池或基准任何一边变化后都要重跑。训练配置的 `exclude_manifests` 会在训练前再检查一遍硬失败项。

版本规则：

- v0.x 是试用期：任何改动（增删实例、改 oracle、改规则或标签、改输入构造）都发布下一个 v0.x。
- 规模达到 60–100 个实例、至少 5 个领域，且你认可规则和标准后，发布 v1.0。之后：增删实例、改 oracle 或规则 → 次版本（v1.1）；改输入构造（`messages()`、五段字段的含义）或任务定义 → 主版本（v2.0）。
- 不同版本的结果不比较；`compare.py` 遇到 manifest 不同会拒绝。
- 每次冻结在 `benchmark/README.md` 的版本历史表登记。

## 7 执行（L3）与人工评审（L4）

### 7.1 L3 执行

对每个候选文件先人工浏览（不越界操作、不改被测实现），再用内网测试框架批量执行，结果填入该运行目录的 `review.csv`：

| 列 | 取值 |
| --- | --- |
| `executed` | yes / no |
| `run_status` | pass / fail / env_error / not_run。正常流"跑通"指业务成功且断言通过；异常流"跑通"指接口按剧本返回约定的错误码和文案，断言通过 |
| `environment_error` | yes / no。账号池、网络、依赖、超时、环境限流等与脚本无关的失败 |

环境问题不算脚本失败，也不算通过，不能从分母删除；修复环境后重跑并保留原记录。

注意：执行通过不等于按剧本实现。一个漏掉剧本写明的文案断言的脚本也能跑通。这类问题由 L2.5（oracle 的 `expect`）和 L4（`follows_scenario`）发现，所以 L3 要和它们一起看。

需要先确认的事：内网框架批量执行时，能否输出每个脚本的通过 / 失败 / 错误类型。能做到的话，可以写一个适配脚本自动回填 `review.csv` 的 L3 三列。

### 7.2 L4 人工评审

按 `rubric.md` 填 `review_verdict`（accept / minor_fix / major_fix / reject）、`follows_scenario`、`invented_api`、`repair_minutes`、`notes`（错误分类开头）。评审时不看组别名，避免先入为主。

## 8 生成、打分、对比

```sh
S=data/private/benchmark/suites/v0.1
python scripts/bench/run_generate.py --suite $S --config configs/local/E001.json --splits dev --experiment E001 --arm B0
python scripts/bench/run_generate.py --suite $S --config configs/local/E001.json --splits dev \
  --adapter runs/train/E001 --experiment E001 --arm B1
python scripts/bench/import_run.py --suite $S --from <A 的输出目录> --splits dev --experiment E001 --arm A \
  --note "<模型 / Skill 版本 / 重试次数>"
python scripts/bench/score.py --run runs/bench/v0.1/E001-B1
python scripts/bench/compare.py runs/bench/v0.1/E001-B0 runs/bench/v0.1/E001-B1 runs/bench/v0.1/E001-A \
  --out runs/records/E001-compare.md
```

- `run_generate.py` 的 `--ids` 只用于调试，结果会标为部分运行。
- `import_run.py` 读取 `<instance_id>.txt` 或 `.py`；缺失的实例计为"未生成"，不从分母删除。
- `score.py` 在 `scores/<时间戳>-s<评分器版本>/` 写 `results.jsonl`、`results.csv`、`summary.json`，并在运行目录生成一次 `review.csv` 模板。填过 `review.csv` 后再运行 `compare.py`，报告会出现 L3、L4 行。
- `compare.py --metric` 可选 `auto_pass`（默认）、`static_pass`、`oracle_pass`。

各层指标：

| 层 | 内容 | 方式 |
| --- | --- | --- |
| L0 形式 | 无围栏、未截断、单代码块、语法正确 | 自动 |
| L1 框架 | 全局规则 | 自动 |
| L2 依据 | 无输入外调用、未重写被测接口、未照抄参考身份；`static_pass` = L0–L2 全过且至少一个测试方法 | 自动 |
| L2.5 剧本实现 | `must_call`、`expect`、`cleanup_required`、`must_not_call`；`oracle_pass` | 自动 |
| AUTO | `auto_pass` = `static_pass` 且 `oracle_pass` | 自动 |
| L3 执行 | 在正确环境中按剧本跑通 | `review.csv` |
| L4 评审 | 是否忠实实现剧本、是否可交付、修复分钟 | `review.csv` |

`sim gold ...` 两行是与 gold 的相似度，换一种合理写法也会降低，只看趋势，不作判定。

## 9 迭代纪律

1. 冻结的版本不改；改动即发布新版本，所有对照组在新版本上重跑。
2. dev 用于迭代；拆出 test 后，test 定稿后只跑一次（[03-evaluation.md](03-evaluation.md) 第 4 节）。
3. 静态判定与执行、评审经常不一致的实例，说明它的 oracle 或剧本需要改进，下个版本修正。
4. 新实例按相同流程（`templates/data-build-prompt.md` → 审核 → `import_pool.py`）加入；从 A 工作流新写出的脚本是 `fresh` 实例的最好来源。
