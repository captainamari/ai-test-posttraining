"""Generate candidates for a frozen suite with one model configuration (one "arm").

Output: runs/bench/<suite>/<run_id>/ with candidates/<instance>.txt, records.json, settings.json, status.json.
Use the same --max-new-tokens and config "generation" for every arm you intend to compare.
"""
import argparse
import sys
from pathlib import Path

import benchlib as B

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate import generate_items  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--suite", required=True)
parser.add_argument("--config", required=True, help="model config, e.g. configs/cpu-long.json")
parser.add_argument("--adapter", help="training run directory; omit for the untrained baseline")
parser.add_argument("--splits", nargs="+", default=["dev"])
parser.add_argument("--ids", nargs="*", help="only these instances (debugging; partial runs are marked as such)")
parser.add_argument("--max-new-tokens", type=int, default=2048)
parser.add_argument("--experiment", required=True, help="e.g. E001")
parser.add_argument("--arm", required=True, help="e.g. B0, B1, B1-lr2e-4")
parser.add_argument("--out-root", default="runs/bench")
args = parser.parse_args()

manifest, instances = B.suite_instances(args.suite, args.splits)
if args.ids:
    instances = [i for i in instances if i["task"]["instance_id"] in args.ids]
if not instances:
    raise SystemExit("no instances for splits %s" % args.splits)
if "test" in args.splits:
    print("NOTE: running the test split. Record it in the experiment log; test is for final decisions only.")
config = B.read(args.config)
run_id = "%s-%s" % (args.experiment, args.arm)
out = Path(args.out_root) / manifest["suite"] / run_id
items = [{"id": i["task"]["instance_id"], "inputs": i["task"]["inputs"]} for i in instances]
generate_items(config, args.adapter, items, args.max_new_tokens, out, lambda _, item: "candidates/%s.txt" % item["id"],
               {"source": "model", "suite": manifest["suite"], "suite_dir": str(args.suite),
                "manifest_sha256": B.sha(Path(args.suite) / "manifest.json"), "splits": args.splits,
                "partial_ids": args.ids or None, "experiment": args.experiment, "arm": args.arm, "run_id": run_id,
                "config_path": args.config, "config_sha256": B.sha(args.config)})
print("done: %s\nnext: python scripts/bench/score.py --run %s" % (out, out))
