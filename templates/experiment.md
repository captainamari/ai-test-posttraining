# 实验 E000

状态：planned / running / failed / completed / interrupted

用法：复制到 `runs/records/E000.md`（内部，不提交）。一个实验只回答一个问题；新数据、新模型、新主要参数用新的编号，并写明相对哪个实验。

## 要回答的问题

假设：

唯一主要变化（相对于哪个实验）：

成功条件（写成可检查的数字或状态）：

停止条件与预算（训练步数、预计时长、生成预算）：

## 固定条件

框架版本（README 的版本表，当前 v0.1）：

代码 commit 与工作区状态：

模型 ID / revision（`models/model-lock.json` 或该模型的 lock 文件）：

训练池文件与 SHA（`runs/audit/` 报告路径）：

基准版本与 manifest SHA（`data/private/benchmark/suites/vX/manifest.json`）：

防泄漏检查报告与结论（`suites/leakage-vX.json`）：

训练配置文件与 SHA：

生成设置（`--max-new-tokens`、配置中的 `generation`，各组必须一致）：

CPU / 内存上限 / 线程 / Python / 依赖：

## 执行记录

| 步骤 | 命令 | 产物目录 | 开始–结束 | 结果 |
| --- | --- | --- | --- | --- |
| 数据门禁 | `python scripts/audit_data.py ...` | `runs/audit/` | | |
| 2 步短跑 | `python scripts/train.py --config ... --run runs/train/E000-check --max-steps 2` | | | |
| 正式训练 | `python scripts/train.py --config ... --run runs/train/E000` | | | |
| B0 生成 | `python scripts/bench/run_generate.py ... --arm B0` | `runs/bench/vX/E000-B0` | | |
| B1 生成 | `python scripts/bench/run_generate.py ... --adapter runs/train/E000 --arm B1` | `runs/bench/vX/E000-B1` | | |
| 打分 | `python scripts/bench/score.py --run ...` | `.../scores/` | | |
| 对比 | `python scripts/bench/compare.py ... --out runs/records/E000-compare.md` | | | |
| 执行与评审 | 填写各运行目录的 `review.csv` 后重新运行 compare | | | |

训练状态（`status.json`）：steps / epochs / `adapter_max_abs_change` / 用时 / 峰值内存：

问题记录引用（`templates/incident.md`）：

## 判断

逐层结果（引用 compare 报告，不手抄全部数字）：

改善的任务及原因：

退步的任务及原因：

与成功条件的对应关系：

尚不能推出的结论（样本数、未审核数据、未执行、混杂因素）：

下一步只改变什么，理由：
