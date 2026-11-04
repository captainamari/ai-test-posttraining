"""Check a frozen suite against the training pool before any training run.

Hard failures (exit 1): shared source_group, identical gold/target, shared script identity,
benchmark gold copied into a training sample's reference.
Soft findings (listed for human review): near-duplicates of the same template with other parameters.
Only split=train rows of the training files are compared, because only they are trained on.
"""
import argparse
import json
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("--suite", required=True, help="suite directory, e.g. data/private/benchmark/suites/v0.1")
parser.add_argument("--train", nargs="+", required=True, help="training pool JSONL files")
parser.add_argument("--near", type=float, default=0.6, help="Jaccard threshold for near-duplicates (default 0.6)")
parser.add_argument("--contain", type=float, default=0.8, help="share of gold fingerprint inside a reference (default 0.8)")
parser.add_argument("--out", help="report path (default <suite>/../leakage-<version>.json)")
args = parser.parse_args()

manifest, instances = B.suite_instances(args.suite)
rules = B.suite_rules(args.suite)
attrs = tuple(rules.get("identity_attrs", ["script_id"]))
train = []
for path in args.train:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("split") == "train":
                train.append(row)

hard, soft = [], []
train_prints = [(row, B.shingles(row["target"]), B.shingles(row["inputs"]["reference"])) for row in train]
for inst in instances:
    task, gold = inst["task"], inst["gold"]
    gold_print = B.shingles(gold)
    gold_ids = B.identities(gold, attrs)
    gold_digest = B.normalized_target_digest(gold)
    for row, target_print, reference_print in train_prints:
        pair = {"instance": task["instance_id"], "train_id": row["id"]}
        if row["source_group"] == task["source_group"]:
            hard.append(dict(pair, kind="same_source_group", detail=task["source_group"]))
        if B.normalized_target_digest(row["target"]) == gold_digest:
            hard.append(dict(pair, kind="identical_answer"))
        shared = gold_ids & B.identities(row["target"], attrs)
        if shared:
            hard.append(dict(pair, kind="shared_identity", detail=sorted(shared)))
        in_reference = gold_ids & B.identities(row["inputs"]["reference"], attrs)
        contained = B.containment(gold_print, reference_print)
        if in_reference or contained >= args.contain:
            hard.append(dict(pair, kind="gold_in_training_reference", detail={"identity": sorted(in_reference),
                                                                              "containment": round(contained, 3)}))
        similarity = B.jaccard(gold_print, target_print)
        if similarity >= args.near:
            soft.append(dict(pair, kind="near_duplicate", similarity=round(similarity, 3)))

report = {"suite": manifest["suite"], "manifest_sha256": B.sha(Path(args.suite) / "manifest.json"),
          "train_files": [{"path": p, "sha256": B.sha(p)} for p in args.train], "train_rows": len(train),
          "thresholds": {"near": args.near, "contain": args.contain},
          "hard": hard, "soft": sorted(soft, key=lambda x: -x["similarity"]),
          "verdict": "fail" if hard else ("review" if soft else "pass")}
out = Path(args.out) if args.out else Path(args.suite).parent / ("leakage-%s.json" % manifest["suite"])
B.write(out, report)
print("verdict=%s hard=%d soft=%d report=%s" % (report["verdict"], len(hard), len(soft), out))
for item in hard[:20]:
    print("  HARD", item)
for item in report["soft"][:20]:
    print("  soft", item)
if hard:
    raise SystemExit(1)
