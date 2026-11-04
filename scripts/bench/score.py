"""Score one benchmark run (or the suite's gold answers) with static and per-instance oracle checks.

  python scripts/bench/score.py --run runs/bench/v0.1/E001-B1
  python scripts/bench/score.py --gold --suite data/private/benchmark/suites/v0.1 --splits dev test --out runs/bench/v0.1/gold

Results go to <run>/scores/<timestamp>-s<scorer version>/; earlier score directories are kept.
A review.csv template is created once in the run directory for execution (L3) and human review (L4).
"""
import argparse
import csv
import datetime
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("--run", help="run directory produced by run_generate.py or import_run.py")
parser.add_argument("--gold", action="store_true", help="score the gold answers (calibration / upper bound)")
parser.add_argument("--suite", help="required with --gold")
parser.add_argument("--splits", nargs="+", help="with --gold; default all")
parser.add_argument("--out", help="with --gold: output run directory")
args = parser.parse_args()

if args.gold:
    if not (args.suite and args.out):
        parser.error("--gold needs --suite and --out")
    run, suite_dir = Path(args.out), args.suite
    manifest, instances = B.suite_instances(suite_dir, args.splits)
    run.mkdir(parents=True, exist_ok=False)
    settings = {"source": "gold", "suite": manifest["suite"], "suite_dir": args.suite, "splits": args.splits,
                "manifest_sha256": B.sha(Path(args.suite) / "manifest.json"), "experiment": "gold", "arm": "gold",
                "run_id": "gold"}
    B.write(run / "settings.json", settings)
    candidates = {i["task"]["instance_id"]: (i["gold"], {"hit_token_limit": False}) for i in instances}
else:
    if not args.run:
        parser.error("--run is required")
    run = Path(args.run)
    settings = B.read(run / "settings.json")
    suite_dir = args.suite or settings["suite_dir"]
    manifest, instances = B.suite_instances(suite_dir, settings.get("splits"))
    if B.sha(Path(suite_dir) / "manifest.json") != settings["manifest_sha256"]:
        raise SystemExit("run was generated against a different suite manifest; regenerate instead of rescoring")
    if settings.get("partial_ids"):
        instances = [i for i in instances if i["task"]["instance_id"] in settings["partial_ids"]]
    records = {r["id"]: r for r in B.read(run / "records.json")}
    candidates = {}
    for task_id, record in records.items():
        candidates[task_id] = ((run / record["file"]).read_text(encoding="utf-8"), record)

rules = B.suite_rules(suite_dir)
results = []
for inst in instances:
    task = inst["task"]
    if task["instance_id"] in candidates:
        raw, record = candidates[task["instance_id"]]
        result = B.score_candidate(raw, record.get("hit_token_limit", False), inst, rules)
    else:
        record, result = {}, B.missing_result(inst, rules)
    results.append({"id": task["instance_id"], "split": task["split"], "source_group": task["source_group"],
                    "tags": task.get("tags", {}), "result": result, "reasons": B.failure_reasons(result),
                    "input_tokens": record.get("input_tokens"), "output_tokens": record.get("output_tokens"),
                    "seconds": record.get("seconds")})

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
out = run / "scores" / ("%s-s%s" % (stamp, B.SCORER_VERSION))
out.mkdir(parents=True, exist_ok=False)
with (out / "results.jsonl").open("w", encoding="utf-8") as stream:
    for item in results:
        stream.write(B.json_line(item))
flat = []
for item in results:
    r = item["result"]
    flat.append({"instance_id": item["id"], "split": item["split"], "source_group": item["source_group"],
                 **{"tag_" + k: v for k, v in item["tags"].items()},
                 "auto_pass": int(r["auto_pass"]), "static_pass": int(r["static_pass"]), "oracle_pass": int(r["oracle_pass"]),
                 "syntax_ok": int(r["syntax_ok"]), "framework_ok": int(r["framework_ok"]), "fence_free": int(r["fence_free"]),
                 "not_truncated": int(r["not_truncated"]), "discovered": r["discovered"],
                 "must_call": "%d/%d" % (r["must_call_total"] - len(r["must_call_missing"]), r["must_call_total"]),
                 "expect_full": "%d/%d" % (sum(e["hit"] == "full" for e in r["expect"]), len(r["expect"])),
                 "cleanup": "%d/%d" % (r["cleanup_total"] - len(r["cleanup_missing"]), r["cleanup_total"]),
                 "input_tokens": item["input_tokens"] or "", "output_tokens": item["output_tokens"] or "",
                 "seconds": round(item["seconds"], 1) if item["seconds"] else "", "artifact_sha": r["artifact_sha"],
                 "reasons": " | ".join(item["reasons"])})
with (out / "results.csv").open("w", encoding="utf-8", newline="") as stream:
    columns = list(dict.fromkeys(k for row in flat for k in row))
    writer = csv.DictWriter(stream, columns)
    writer.writeheader()
    writer.writerows(flat)
summary = {"run": str(run), "settings": {k: settings.get(k) for k in ("experiment", "arm", "run_id", "source", "splits")},
           "suite": manifest["suite"], "manifest_sha256": settings["manifest_sha256"], "scorer_version": B.SCORER_VERSION,
           "rules_sha256": manifest["files"]["rules.json"],
           "metrics": [{"label": a, "num": b, "den": c} for a, b, c in B.metric_rows(results)]}
B.write(out / "summary.json", summary)
review = run / "review.csv"
if not review.exists():
    with review.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, B.REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows({"instance_id": item["id"]} for item in results)
print("%s  suite=%s  tasks=%d  -> %s" % (settings.get("run_id"), manifest["suite"], len(results), out))
for label, num, den in B.metric_rows(results):
    print("  %-40s %s/%s" % (label, num if isinstance(num, int) else round(num, 1), den))
failing = [item for item in results if not item["result"]["auto_pass"]]
for item in failing[:15]:
    print("  FAIL %s: %s" % (item["id"], "; ".join(item["reasons"][:6])))
