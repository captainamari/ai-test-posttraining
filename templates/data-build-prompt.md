# 训练数据构建提示词（交给 AI 执行）

用法：复制本文件到 `data/private/build/prompt-<批次编号>.md`（`data/private/` 已被 git 忽略），只填写第 1 节，然后把整个文件交给有读取仓库权限的 AI。本模板不含公司信息，填好的副本不要放进公开目录。完整流程见 `docs/01-data.md`。

---

## 1 需要你填写的内容

```text
框架仓库路径:      /绝对路径/framework-repo
API 封装仓库路径:  /绝对路径/api-repo
存量测试仓库路径:  /绝对路径/tests-repo
目标领域目录:      tests-repo 下的相对路径，可写多个，例如 order/ 、payment/
本批样本数量:      先填 3（试做），确认后再扩大（例如 60）
每个近重复家族最多: 3 条（同一模板只改参数的脚本算一个家族）
工程根目录:        /root/ai-works/ai-test-posttraining
构建目录:          {工程根目录}/data/private/build/        （盘点、框架约定、构建脚本）
候选目录:          {工程根目录}/data/private/candidates/   （待审样本）
批次编号:          B002
```

可选补充（没有就写"无"）：

```text
需求/规则文档路径:  
接口文档路径:       
不要使用的文件或目录: 
单条样本 token 预算: 默认 8000（超过要报告，不要自行截断；B001 实测 4849~6674）
```

范围（默认如下，需要时修改）：

```text
收录:   有明确测试剧本（前置、动作、预期写清楚）的纯接口业务流脚本，正常流和异常流都收
排除:   系统类测试（限流、性能、压测、稳定性、容灾、监控告警）；需要操作手机界面或 OCR 的脚本；没有明确剧本的脚本
注意:   规则文档里写明的业务配额（如"每用户每日最多 N 笔"）属于业务规则，收录；网关/系统层面的限流属于系统类，排除
```

---

## 2 任务背景（给 AI 读）

我们要为一个开源代码模型准备监督微调（SFT）数据。模型的任务是：**根据人工编写的测试剧本，加上契约（业务规则、接口）和框架约定，忠实地写出测试脚本**。测什么、预期是什么，都由剧本决定；模型不设计用例，不补充剧本以外的测试。

每条样本是一个 JSON 对象：`inputs` 是模型使用时会看到的全部资料，`target` 是人工编写并通过评审的最终测试脚本。模型只能看到你写入 `inputs` 的文本，读不到仓库，所以必须把真正用到的内容复制成文本放进去，不能只写路径。

三个仓库的角色：

- 框架仓库：基于 unittest 重构的测试框架（基类、fixture、断言、清理、执行入口）。
- API 封装仓库：测试里调用的接口封装。
- 存量测试仓库：按领域归类的已有测试脚本，作为 `target` 与 `reference` 的来源。

## 3 硬性规则

1. 三个仓库一律只读。不得修改、格式化、提交、重命名其中任何文件。
2. 只能向"构建目录"和"候选目录"写文件。不得写入 `data/private/train/` 和 `data/private/benchmark/`。不使用网络，不把内容发到仓库之外。
3. `target` 必须逐字复制存量脚本，不得改写、补全、翻译或去掉注释。
4. 不得编造业务规则、API 签名、参数含义。找不到就在 `build_notes.gaps` 里记录，不要猜。
5. 凭证、令牌、密码、内部域名等敏感信息：用 `<REDACTED>` 替换并记录在 `build_notes.redactions`，不要原样写入。
6. 你不是审核人。所有样本的 `review_status` 一律写 `"pending"`，不得写 `"approved"`。
7. 遇到仓库读不到、目录不存在、结构与描述不符，停下来报告，不要绕过。
8. 每个阶段末尾标注了"停止点"，必须停下等待我确认，不得连续执行到下一阶段。
9. 只收第 1 节"范围"内的脚本。范围外的脚本在盘点中列出并标注"超出范围"，不构建样本。

## 4 执行步骤

### 阶段 A：盘点（停止点）

1. 记录三个仓库的 git commit SHA 与工作区是否干净（`git rev-parse HEAD`、`git status --short`）。
2. 在目标领域目录下列出测试文件：路径、行数、使用的基类、调用的 API 数量。
3. 概括框架约定：测试类继承什么基类，fixture/前置/清理怎么写，断言用什么，文件骨架，如何执行。给出代码出处（文件与行号）。
4. 概括 API 封装风格：目录结构、模块命名、函数签名风格、有无 docstring、错误约定。
5. 把盘点写入 `{构建目录}/context/inventory-{批次编号}.md`，并在回复里列出：
   - 你准备选哪几个测试文件、依据是什么（正常流和异常流都要有，覆盖参数校验、额度/边界、状态、幂等、资源清理中的不同类型）。
   - 超出范围而未选的文件及原因。
   - 你发现的风险：文件特别长、依赖隐藏全局状态、API 无文档、规则找不到来源、近重复脚本。

**停止点 A：等我确认选哪些文件。**

### 阶段 B：生成"框架约定"文本（停止点）

写出一份给模型阅读的框架约定，保存为 `{构建目录}/context/framework.md`（已存在时先读取，只做增补并在回复中列出改动）：

- 只包含写脚本所需的规则：基类、导入方式、fixture/前置/清理、断言约定、命名、文件骨架、必须或禁止的做法。
- 控制在 1000 token 以内（B001 实测 645），用简洁条目，不贴大段框架源码。
- 每一条都要来自框架仓库或存量脚本的实际做法，在文末列出出处。

**停止点 B：等我审阅 `framework.md`。**

### 阶段 C：为每个选定的测试文件构建一条样本

对每个已确认的文件，按下表填写 `inputs` 五个字段：

| 字段 | 内容 | 来源与做法 |
| --- | --- | --- |
| `rules` | 判断本场景所需的业务规则原文 | 优先取需求/规则文档；没有文档时，只能从脚本的 docstring、注释、用例名推断，并在 `build_notes.rules_basis` 写 `inferred_from_script`，在 `gaps` 说明需要人工补规则来源 |
| `scenario` | 测试剧本：前置、动作、**预期**（正常流写成功码和应观察到的副作用；异常流写契约约定的错误码和文案） | 取自脚本中的剧本或注释；没有就按脚本行为改写为文字，并标注 `rewritten_from_script`。脚本断言了而剧本没写的预期，要补进剧本并在 `gaps` 说明，否则模型无从得知 |
| `api` | 目标脚本实际调用到的接口：import 路径、签名、参数含义、返回值、错误与副作用 | 用 `ast` 从目标脚本提取被调用的符号，再到 API 仓库定位其定义；逐个复制签名与 docstring。找不到定义的符号写入 `gaps` |
| `framework` | 阶段 B 确认的 `framework.md` 全文 | 每条样本相同 |
| `reference` | 1 到 2 个同领域、相似场景的存量脚本全文 | 必须排除目标脚本本身及其近重复（同模板仅改参数）。确实没有就写"无参考脚本" |

`target` 是目标脚本全文，逐字复制。

其余字段：

- `id`：`{批次编号}-{序号三位}`，例如 `B001-001`，不用内部业务名。
- `source_group`：同一领域下同一业务操作或脚本家族使用同一个值。同组样本必须在同一个 `split`。
- `split`：给出建议：`train`（进训练池）或 `dev`（建议进基准），理由写在 `build_notes.split_reason`。建议进基准的样本优先选择：独立分组、规则来源清楚、剧本写明了具体预期（错误码、文案、副作用）。最终由人决定。
- `tags`：对象，至少包含 `flow`（`normal` 正常流 / `exception` 异常流）、`domain`（领域目录名）、`scenario_type`（param_validation / limit / state / idempotent / cleanup / format / other）。
- `origin`：从历史脚本重建时写 `"reconstructed"`。
- `review_status`：固定 `"pending"`。
- `provenance`：字符串数组，每项形如 `"tests-repo@<SHA>:<相对路径>"`，覆盖 target、reference、API 定义、规则文档的出处。
- `build_notes`：对象，记录 `rules_basis`、`gaps`、`redactions`、`split_reason`、`near_duplicates`、`estimated_tokens`。训练不会使用这个字段，仅供审核。
- 去重：同一模板只改参数的近重复脚本算一个家族，使用同一个 `source_group`；每个家族最多保留第 1 节规定的条数，其余列在 `near_duplicates`。建议进基准的家族只取 1 条，且整个家族都不再进训练池。

### 阶段 D：试做 2 到 3 条（停止点）

先只构建 2 到 3 条，写入 `{候选目录}/candidates-{批次编号}.jsonl`（每行一个 JSON 对象，UTF-8，`ensure_ascii=False`）。

构建过程要写成可重跑的脚本，保存在 `{构建目录}/tools/`（已有 `build_samples.py` 时复用并扩展，批次相关的选样写在 `spec_{批次编号}.py`）：提取、组装、校验逻辑放在脚本里，而不是手工拼接，之后相同规则可复用到使用阶段。

回复时展示：

- 第一条样本的完整 JSON。
- 每条样本的估算 token 数（有模型 tokenizer 时用 tokenizer 计数；没有时用字符数 / 3，说明所用方法。B001 用字符数 / 2 比实测高估约 1.5 倍）。准确长度由人运行 `python scripts/audit_data.py <文件> --tokens --config <配置>` 得到。
- 所有 `gaps` 与风险。

**停止点 D：等我确认格式、长度和字段内容，再扩大数量。**

### 阶段 E：批量构建与自检

确认后构建到"本批样本数量"。对每条样本自检，结果写入 `{候选目录}/candidates-{批次编号}-checks.md`：

1. JSON 可解析，且有 `id`、`source_group`、`split`、`tags`、`origin`、`review_status`、`provenance`、`inputs`（五个字段全部非空）、`target`。
2. `ast.parse(target)` 成功。
3. 目标脚本调用的每一个项目内符号，都能在 `inputs.api` 中找到；找不到的列出（这是"答案依赖的知识不在输入里"的信号）。
4. `target` 与其他样本无完全相同；`reference` 不含 `target` 本身。
5. 同一 `source_group` 没有跨 split。
6. 估算 token 数是否超过预算，超出的列出，不要截断。
7. 没有残留的凭证类字符串。

最后汇报：样本数、split 分布、`gaps` 清单、需要我人工补充的问题清单。

## 5 交付物

```text
{候选目录}/candidates-{批次编号}.jsonl         待审样本（全部 pending）
{候选目录}/candidates-{批次编号}-checks.md     自检结果
{构建目录}/context/inventory-{批次编号}.md     仓库盘点
{构建目录}/context/framework.md                框架约定
{构建目录}/tools/build_samples.py              可重跑的构建脚本
{构建目录}/tools/spec_{批次编号}.py            本批选样、分组、划分
```

## 6 你完成后我会做什么（AI 不要做）

1. 逐条审核业务含义，补充规则来源，处理 `gaps`，修正 `tags`。
2. 决定去向：进训练池的样本把 `review_status` 改为 `approved`，用 `scripts/select_rows.py` 复制到 `data/private/train/`；进基准的样本用 `scripts/bench/import_pool.py` 导入 `data/private/benchmark/pool/`，在那里审核判定标准。同一条样本只能去一处。
3. 运行 `python scripts/audit_data.py data/private/train/*.jsonl --out runs/audit/<批次>.json --tokens --config <配置>`，通过后才用于训练。
