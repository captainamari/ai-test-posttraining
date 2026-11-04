"""Training-pool gate: fields, review label, groups, exact duplicates, syntax.

Optional:
  --exclude-manifest  also check against frozen benchmark suites (same check train.py runs)
  --tokens --config   count real tokens with the configured model's tokenizer and compare with max_length
"""
import argparse
import os
from collections import Counter

from common import check_benchmark_exclusion, data_paths, load_data, read, sha, write

parser = argparse.ArgumentParser()
parser.add_argument("data", nargs="+", help="one or more training-pool JSONL files")
parser.add_argument("--out", required=True)
parser.add_argument("--exclude-manifest", nargs="*", default=[])
parser.add_argument("--tokens", action="store_true")
parser.add_argument("--config", default="configs/cpu-smoke.json")
args = parser.parse_args()
rows = load_data(args.data)
if args.exclude_manifest:
    check_benchmark_exclusion(rows, args.exclude_manifest)
report = {"files": [{"path": str(p), "sha256": sha(p)} for p in data_paths(args.data)], "samples": len(rows),
          "splits": dict(Counter(r["split"] for r in rows)),
          "groups": dict(Counter(r["source_group"] for r in rows if r["split"] == "train")),
          "origins": dict(Counter(r["origin"] for r in rows)),
          "benchmark_exclusions": [{"path": p, "sha256": sha(p)} for p in args.exclude_manifest],
          "checked": ["required_fields", "approval_label", "group_split", "exact_target_duplicates", "python_syntax"]
                     + (["benchmark_exclusion"] if args.exclude_manifest else []),
          "not_checked": ["business_truth", "approval_identity", "near_duplicates", "runtime_behavior", "publication_rights"]}
if args.tokens:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from transformers import AutoTokenizer
    from common import messages
    config = read(args.config)
    tokenizer = AutoTokenizer.from_pretrained(read(config["model_lock"])["local_path"], local_files_only=True)
    lengths = []
    for row in rows:
        prompt = len(tokenizer.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True))
        answer = len(tokenizer(row["target"])["input_ids"])
        lengths.append({"id": row["id"], "prompt": prompt, "answer": answer, "total_approx": prompt + answer + 2})
    totals = sorted(x["total_approx"] for x in lengths)
    report["tokens"] = {"config": args.config, "max_length": config["max_length"], "min": totals[0],
                        "median": totals[len(totals) // 2], "max": totals[-1],
                        "over_max_length": [x["id"] for x in lengths if x["total_approx"] > config["max_length"]],
                        "answers_max": max(x["answer"] for x in lengths), "per_sample": lengths}
write(args.out, report)
print({k: v for k, v in report.items() if k != "tokens"})
if args.tokens:
    print({k: v for k, v in report["tokens"].items() if k != "per_sample"})
