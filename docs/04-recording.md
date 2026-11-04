# 记录实验与公开发布

## 1 runs/ 目录约定

`runs/` 已被 git 忽略，是内部证据区。

```text
runs/
  records/                 人写的记录（每个实验一份，最需要长期保留）
    E001.md                由 templates/experiment.md 复制
    E001-compare.md        compare.py --out 的输出
  audit/E001.json          训练池门禁报告
  train/
    E001-check/            2 步短跑
    E001/                  正式训练（config、data-manifest、metrics、status、adapter/ ……）
    E001.log
  bench/<基准版本>/<实验>-<组>/   生成与评分，例如 runs/bench/v0.1/E001-B1/
    settings.json records.json candidates/<instance_id>.txt
    scores/<时间戳>-s<评分器版本>/{results.jsonl, results.csv, summary.json}
    review.csv             执行与人工评审（L3、L4），由 score.py 首次生成模板
```

所有工具都拒绝覆盖已有目录；重做就用新目录名（`E001-B1-rerun`）。评分器或规则变化后对旧运行重新打分，会写入新的 `scores/` 子目录，旧分数保留。

## 2 一个实验一份记录

1. 实验前复制 `templates/experiment.md` 为 `runs/records/E001.md`。填：要回答的问题、唯一变化项、固定条件（基准版本、防泄漏结论、模型 lock、训练池文件 SHA、生成设置）、预算、成功条件。
2. 执行中按模板第"执行记录"表逐步登记产物路径；原始日志就是证据，不必手抄每个 loss。
3. 执行后填"判断"：看到了什么、能说什么、不能说什么、下一轮只改什么。失败也是一个完成的实验。
4. 不要用后来的理解改写当时的记录；新的理解写进下一个实验，并引用上一个。

新数据批次、新模型、新的主要参数，都开新编号。

## 3 遇到问题

用 `templates/incident.md`：最小复现、环境、原始错误、假设、验证动作、观察结果、状态（suggested / tested / resolved）。没执行过的建议不能记成解决方案。

例：loss 下降但生成退步，事实是"两个指标方向不同"。可能原因有过拟合、监督目标错误、生成截断等，逐个验证，不把第一个猜测写成根因。

## 4 可沉淀的经验写到哪里

| 经验类型 | 写到 |
| --- | --- |
| 框架约定的可机检部分（基类、必需方法、禁用调用） | `data/private/benchmark/rules/framework-vN.json`（见 05 第 5 节） |
| 评审时的判断标准与正反例 | `data/private/benchmark/rubric.md` |
| 数据构建时反复出现的问题 | `templates/data-build-prompt.md` 的硬性规则，或 `data/private/build/prompt-<批次>.md` |
| 评分器漏判或误判 | `tests/test_bench.py` 增加一个回归用例，再改 `scripts/bench/benchlib.py` |
| 调参经验 | 实验记录的"判断"部分；稳定后补进 02 第 8 节的诊断表 |

写经验时带上适用条件和验证方法。"聊天模板前缀检查失败时先核对 tokenizer 与模板版本"可复用；"效果差就换模板"不可复用。

## 5 公开仓库

公开：通用代码、`data/public/` 的虚构样本与实例、模板、经审阅的报告。内部：`data/private/`、`models/`、`runs/`、`configs/local/`（均已忽略）。`.gitignore` 不保护已被跟踪的文件，也不等于发布授权。

发布前：选择许可证；检查暂存文件和提交历史；日志可能包含完整提示与公司代码，适配器权重也可能记住训练内容，不能因为"不是文本"就公开。

| 可贡献给社区的 | 需要的证据 |
| --- | --- |
| 测试脚本生成的评测方法与工具 | 虚构实例、评分器回归测试 |
| 数据重建与防泄漏工具 | 小型可复现数据 |
| CPU 训练实测记录 | CPU 型号、版本、序列长度、实测耗时与内存 |
| 微调适配器 | 基础模型 SHA、配置、许可、模型卡（`templates/model-card.md`）和对照结果 |

顺序：先公开工具和教学数据；完成真实训练与重新加载后公开流程验证；完成独立基准评测后才公开效果报告。数据卡、模型卡模板：`templates/data-card.md`、`templates/model-card.md`。
