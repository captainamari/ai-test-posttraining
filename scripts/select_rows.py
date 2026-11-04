"""Copy reviewed candidate rows into a training-pool batch file.

Rows must already be review_status=approved (edited by the reviewer, never by the build AI).
Rows chosen for the benchmark go through bench/import_pool.py instead and must not be copied here.
"""
import argparse
import json
from pathlib import Path

from common import load_data

parser = argparse.ArgumentParser()
parser.add_argument("--from", dest="source", required=True, help="candidates JSONL")
parser.add_argument("--out", required=True, help="new file under data/private/train/")
parser.add_argument("--split", default="train", help="select rows with this split (default train)")
parser.add_argument("--ids", nargs="*", help="select only these ids")
parser.add_argument("--exclude-ids", nargs="*", default=[], help="ids reserved for the benchmark")
args = parser.parse_args()

out = Path(args.out)
if out.exists():
    raise SystemExit("refusing to overwrite %s; create a new batch file" % out)
rows = [json.loads(line) for line in Path(args.source).read_text(encoding="utf-8").splitlines() if line.strip()]
chosen = [r for r in rows if (args.ids is None or r["id"] in args.ids) and r["id"] not in args.exclude_ids
          and (args.ids is not None or r.get("split") == args.split)]
unknown = set(args.ids or []) - {r["id"] for r in rows}
if unknown:
    raise SystemExit("ids not found: " + ", ".join(sorted(unknown)))
pending = [r["id"] for r in chosen if r.get("review_status") != "approved"]
if pending:
    raise SystemExit("not approved yet: " + ", ".join(pending))
for row in chosen:
    row["split"] = "train"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in chosen), encoding="utf-8")
load_data(out)
print("wrote %d rows to %s: %s" % (len(chosen), out, ", ".join(r["id"] for r in chosen)))
