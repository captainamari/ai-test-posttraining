"""Bring outputs produced elsewhere (e.g. workflow A, a hosted model) into the benchmark run format.

Put one file per instance in a directory, named <instance_id>.txt or <instance_id>.py, as raw output
(do not fix it by hand; record human repairs in review.csv instead).
"""
import argparse
import datetime
import shutil
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("--suite", required=True)
parser.add_argument("--from", dest="source", required=True, help="directory with <instance_id>.txt|.py files")
parser.add_argument("--splits", nargs="+", default=["dev"])
parser.add_argument("--experiment", required=True)
parser.add_argument("--arm", required=True, help="e.g. A")
parser.add_argument("--note", default="", help="model, workflow, skill version, retries, tools used")
parser.add_argument("--out-root", default="runs/bench")
args = parser.parse_args()

manifest, instances = B.suite_instances(args.suite, args.splits)
run_id = "%s-%s" % (args.experiment, args.arm)
out = Path(args.out_root) / manifest["suite"] / run_id
(out / "candidates").mkdir(parents=True, exist_ok=False)
records, absent = [], []
for inst in instances:
    task_id = inst["task"]["instance_id"]
    found = [p for p in (Path(args.source) / (task_id + ".txt"), Path(args.source) / (task_id + ".py")) if p.is_file()]
    if not found:
        absent.append(task_id)
        continue
    shutil.copyfile(found[0], out / "candidates" / (task_id + ".txt"))
    records.append({"id": task_id, "file": "candidates/%s.txt" % task_id, "hit_token_limit": False})
B.write(out / "records.json", records)
B.write(out / "settings.json", {"source": "imported", "imported_from": str(args.source), "note": args.note,
                                "imported_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                                "suite": manifest["suite"], "suite_dir": str(args.suite),
                                "manifest_sha256": B.sha(Path(args.suite) / "manifest.json"), "splits": args.splits,
                                "experiment": args.experiment, "arm": args.arm, "run_id": run_id})
B.write(out / "status.json", {"status": "generation_completed", "count": len(records), "quality_verdict": "not_evaluated"})
print("imported %d, absent %d (scored as not generated): %s" % (len(records), len(absent), ", ".join(absent)))
