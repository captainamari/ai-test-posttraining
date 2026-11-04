# 每一轮的操作清单

本页是索引式清单；每步的细节在对应文档。命令都在工程根目录、已激活 `.venv` 时执行：

```sh
cd /root/ai-works/ai-test-posttraining && source .venv/bin/activate
```

## 一次性准备

- [x] 隔离环境与依赖（02 第 1 节）。
- [x] 下载并锁定模型 `models/model-lock.json`（02 第 2 节）。
- [x] review 基准设计与标准，把团队经验写进去（05 第 5 节；清单在 `data/private/benchmark/README.md`）。（部分：审核 B002 数据时同步核对；团队经验补充仍待做）
- [x] 选定基准实例所在的脚本家族（`source_group`），在构建训练数据之前先保留出来（01 第 6 节）。（全 PartUAT 范围 14 个家族，`data/private/build/context/selection-all-B002-proposal.md`）
- [x] 构建并审核训练批次 B002（目标 60 条），放入 `data/private/train/B002.jsonl`（01）。（60 条构建+人工审核 approved；3 条超 max_length 8192（B002-042/043/059）暂移出训练池，57 条入池，`runs/audit/B002.json`）
- [x] 审核基准实例的判定标准，冻结基准 v0.1（12–16 个实例，全部 dev），跑防泄漏检查（05 第 3、4、6 节）。（14 个 B002-061~074 实例逐条清理草稿噪声并 approve；`build_suite.py --version v0.1` 已冻结；`check_leakage.py` 初次命中 1 条 hard（B002-073 与训练样本 B002-045 的 reference 文本重叠 80.4%，同一 usecase 家族的姊妹脚本），已将 B002-045 的 `split` 改为 `test` 隔离出训练集；复查后 `hard=0, soft=10`（soft 均为同家族不同参数的正常相似，不阻塞））
- [ ] 把 v0.1 的 manifest 写进训练配置的 `exclude_manifests`（02 第 3 节）。
- [ ] 确认内网执行器批量运行脚本的方式，用于 L3（05 第 7 节）。

## 每一轮

一轮 = 一个实验编号（E001、E002……），只回答一个问题、只改一个主要因素。

| # | 做什么 | 命令 / 位置 | 产物 | 细节 |
| --- | --- | --- | --- | --- |
| 1 | 写下本轮问题和唯一变化 | 复制 `templates/experiment.md` → `runs/records/E001.md` | 实验记录 | 04 |
| 2 | （需要新数据时）构建候选样本 | 填 `templates/data-build-prompt.md` → `data/private/build/prompt-B00X.md`，交给 AI | `data/private/candidates/candidates-B00X.jsonl` | 01 |
| 3 | 人工审核并分流 | 训练样本：改 `review_status`，`scripts/select_rows.py`；基准样本：`scripts/bench/import_pool.py` | `data/private/train/B00X.jsonl`、`benchmark/pool/<id>/` | 01、05 |
| 4 | （基准有变化时）冻结新版本 | `scripts/bench/build_suite.py --version v0.2` | `benchmark/suites/v0.2/` | 05 |
| 5 | 防泄漏检查（训练池或基准变化后必做） | `scripts/bench/check_leakage.py` | `suites/leakage-v0.X.json` | 05 |
| 6 | 准备配置 | 复制 `configs/cpu-long.json` → `configs/local/E001.json`，只改本轮变化项 | 配置 | 02 |
| 7 | 训练池门禁 + 真实长度 | `scripts/audit_data.py ... --tokens --exclude-manifest ...` | `runs/audit/E001.json` | 01、02 |
| 8 | 2 步短跑 | `scripts/train.py --run runs/train/E001-check --max-steps 2` | 训练产物 | 02 |
| 9 | 正式训练（后台） | `nohup ... scripts/train.py --run runs/train/E001 ...` | 适配器 | 02 |
| 10 | B0 生成（同一基准版本 + 模型 + 生成设置只需做一次，可复用） | `scripts/bench/run_generate.py --arm B0` | `runs/bench/v0.1/E001-B0/` | 05 |
| 11 | B1 生成 | `scripts/bench/run_generate.py --adapter runs/train/E001 --arm B1` | `runs/bench/v0.1/E001-B1/` | 05 |
| 12 | 自动打分 | `scripts/bench/score.py --run ...`（每个运行目录一次） | `scores/`、`review.csv` 模板 | 05 |
| 13 | 执行与人工评审 | 在内网批量执行候选脚本，按 rubric 填各运行目录的 `review.csv` | L3、L4 | 03、05 |
| 14 | 对比 | `scripts/bench/compare.py B0目录 B1目录 [A目录] --out runs/records/E001-compare.md` | 对比报告 | 03 |
| 15 | 判断并决定下一轮 | 填实验记录"判断"部分；按 02 第 8 节的诊断表选下一步 | 实验记录 | 02、04 |

基准 v0.x 只有 dev。规模扩大、拆出 test 后，test 只在方案确定后运行一次（03 第 4 节）。

## 命令模板（以 E001、基准 v0.1、批次 B002 为例）

```sh
# 3 分流：保留给基准的样本不进训练池
python scripts/select_rows.py --from data/private/candidates/candidates-B002.jsonl \
  --exclude-ids B002-061 B002-062 --out data/private/train/B002.jsonl
python scripts/bench/import_pool.py --from data/private/candidates/candidates-B002.jsonl --ids B002-061 B002-062

# 4–5 冻结与防泄漏
python scripts/bench/build_suite.py --version v0.1 --check        # 只校验
python scripts/bench/build_suite.py --version v0.1 --note "首个试用版本"
python scripts/bench/check_leakage.py --suite data/private/benchmark/suites/v0.1 --train data/private/train/*.jsonl

# 7 门禁（配置里 data 列出全部训练批次文件，exclude_manifests 指向当前基准）
python scripts/audit_data.py data/private/train/*.jsonl --out runs/audit/E001.json \
  --tokens --config configs/local/E001.json \
  --exclude-manifest data/private/benchmark/suites/v0.1/manifest.json

# 8–9 训练
python scripts/train.py --config configs/local/E001.json --run runs/train/E001-check --max-steps 2
nohup python scripts/train.py --config configs/local/E001.json --run runs/train/E001 > runs/train/E001.log 2>&1 &
tail -c 300 runs/train/E001.log | tr '\r' '\n' | tail -2      # 看进度
cat runs/train/E001/status.json                                 # 结束后

# 10–12 生成与打分
S=data/private/benchmark/suites/v0.1
nohup python scripts/bench/run_generate.py --suite $S --config configs/local/E001.json --splits dev \
  --experiment E001 --arm B0 > runs/E001-B0.log 2>&1 &
nohup python scripts/bench/run_generate.py --suite $S --config configs/local/E001.json --splits dev \
  --adapter runs/train/E001 --experiment E001 --arm B1 > runs/E001-B1.log 2>&1 &
python scripts/bench/score.py --run runs/bench/v0.1/E001-B0
python scripts/bench/score.py --run runs/bench/v0.1/E001-B1

# 14 对比
python scripts/bench/compare.py runs/bench/v0.1/E001-B0 runs/bench/v0.1/E001-B1 --out runs/records/E001-compare.md
```

两个生成任务同时运行时会争用 CPU；按顺序运行耗时更可预测。

## 时间预算（本机实测，8 线程，见 VALIDATION.md）

| 步骤 | 实测 | 估算方法 |
| --- | --- | --- |
| 训练，5k–7k token / 样本 | 每步 50–134 秒，均值约 83 秒 | 步数 × 83 秒；步数 = 样本数 × epoch ÷（batch × 梯度累积） |
| 生成，输入约 4.5k token | 约 4 token/秒；1000 token 的脚本约 4–5 分钟 | 实例数 × 平均输出 token ÷ 4 |
| 例：60 条训练样本 × 3 epoch | 180 步 ≈ 4 小时 | |
| 例：16 个 dev 实例 × 1 组 | ≈ 1–1.5 小时 | |

线程数尚未调优（容器配额 32 核）；先做一次线程对比实验再估算大规模运行。
