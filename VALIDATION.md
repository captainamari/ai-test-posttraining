# 起步包验证范围

2026-10-28，本地 Windows / Python 3.12.14。

- 运行 `python -m unittest discover -s tests -v`：8 项通过，其中执行了 3 个手写教学参考测试。
- toy 数据 audit：3 条，train/dev/test 各 1 条；3 个独立教学分组。
- 所有 Python 文件通过语法解析，JSON 配置与样本可解析；文档本地链接检查通过。
- 标签掩码测试使用替身 tokenizer。实际模型的聊天模板由训练入口在运行时检查，尚未实测。
- 未安装或验证完整 torch/transformers/peft/accelerate 依赖组合，未下载模型，未执行前向/反向、适配器保存加载或模型生成。
- 未进行 CPU 性能测量、业务评估、真实公司数据处理或发布。

因此，本包是准备完成的代码与操作草案。首次模型短跑的成功与问题，需要在目标机器产生记录；当前没有训练时长、质量提升或成本改善结论。

## 目标 CPU 服务器（2026-10-29，Linux / Python 3.10.17）

- 机器：AMD EPYC 9754（KVM），64 个逻辑 CPU（32 核 × 2 线程），内存 247 GiB，无 swap，`/root` 可用约 1 TB。
- 环境：`.venv`，pip 已升至 26.2.2；torch 2.8.0+cpu、transformers 4.57.1、peft 0.17.1、accelerate 1.10.1；`pip check` 无冲突，四个库可导入。
- 在该环境运行 `python -m unittest discover -s tests -v`：8 项通过；toy audit 3 条，train/dev/test 各 1 条，data SHA256 为 `c377b2d8…3690`。
- 本机可访问 huggingface.co（HTTP 200）。pip 默认源为腾讯镜像，torch CPU 包来自 download.pytorch.org。
- 尚未下载模型，未执行前向/反向、适配器保存加载、生成或性能测量。依赖尚未冻结，待短跑通过后再做。

默认依赖与小模型旨在减少首次操作范围，不代表当前所有模型/库的最佳组合。后续修改配置、依赖或代码时，新建实验并重新核对。

## E003 与基准评测（2026-10-30，同一服务器）

- 容器内存上限为 64 GB（cgroup），`free` 显示的 247 GiB 不是可用上限。5k~7k token 序列在 FP32 下，eager 与 sdpa 注意力的训练均因 OOM 被杀（约 61.5 GB），启用 `gradient_checkpointing` 后峰值 22.5 GB，可完成。
- 在 B001（10 条，未审核）上完成 30 步训练：41 分 41 秒，单步 50~134 秒，8 线程。适配器保存、重新加载并生成成功。生成约 4 token/秒（输入约 4.5k token）。
- 在同一 dev 上对照未微调与微调后的输出：微调后的输出在静态指标上更差，观察到复制参考脚本 `script_id` 的现象。dev 仅 2 条，样本数据未审核，不能据此推断一般规律。
- 当时的评分器 `scripts/evaluate.py` 已由 `scripts/bench/` 取代（见下节）。

## 框架整理（2026-11-01，同一服务器）

- 删除了 E001–E003 的全部运行产物（`runs/`）、B001 候选样本与派生数据、旧评分器及其测试。上节的耗时与内存数字是删除前的实测记录，仍可用于估算；E003 的效果观察不再有可复查的产物。B001 的构建工具保留在 `data/private/build/tools/`，可重新生成候选样本。
- 训练池与基准分离：训练池 `data/private/train/`（只含 split=train），基准 `data/private/benchmark/`（pool → 冻结 suite）。训练前按基准 manifest 做排除检查。
- 新增基准工具 `scripts/bench/`（入池、冻结、防泄漏、生成、导入、打分、对比）、`scripts/select_rows.py`，`audit_data.py` 支持多文件、真实 token 长度与基准排除。
- `python -m unittest discover -s tests`：24 项通过（数据门禁与标签掩码 8 项，基准 16 项）。
- 真实模型端到端冒烟：2 步训练（`configs/cpu-long.json` 的副本，指向临时训练池）→ 在 toy 基准上 B0、B1 生成 → 打分 → 对比，以及 `scripts/generate.py`，均跑通；临时产物已删除。只证明流程连通，不涉及效果。
- 尚未完成：基准实例审核与冻结；执行器接入；线程数调优。

## 框架 v0.1（2026-11-01，同一服务器）

- 任务定义调整为"按人工剧本忠实生成脚本"：去掉故障版本（原 L4），原 L5 人工评审改称 L4；`review.csv` 列改为 `executed, run_status, environment_error, review_verdict, follows_scenario, invented_api, repair_minutes, notes`；实例目录不再有 `mutants/`。
- 版本统一为 v0.1：规则 `framework-v0.1.json`（`company-uat-v0.1`）、标签 `company-taxonomy-v0.1`、评审标准 v0.1、`SCORER_VERSION = "0.1"`；第一个冻结的基准将是 v0.1；实验编号从 E001 重新开始（上节的 E003 指整理前的试验）。
- `configs/cpu-long.json`：`data` 指向 `data/private/train/B002.jsonl`，`exclude_manifests` 置空（基准冻结后再填）。
- `python -m unittest discover -s tests`：24 项通过；公开示例 pool 用 toy 规则 `build_suite.py --check` 3 个实例全部就绪。
