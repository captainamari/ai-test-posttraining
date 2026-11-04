"""Turn candidate rows into benchmark pool instances (data/private/benchmark/pool/<id>/).

The oracle is pre-filled from the gold answer as a DRAFT to save typing. A reviewer must check every
item against the rules and scenario, fix it, and set status=approved; build_suite.py refuses drafts.
Rows imported here belong to the benchmark: never copy them into the training pool.
"""
import argparse
import ast
import json
import re
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("--from", dest="source", required=True, help="candidates JSONL")
parser.add_argument("--ids", nargs="+", required=True)
parser.add_argument("--pool", default="data/private/benchmark/pool")
parser.add_argument("--rules", default="data/private/benchmark/rules/framework-v0.1.json")
parser.add_argument("--taxonomy", default="data/private/benchmark/taxonomy.json")
parser.add_argument("--split", help="override split (dev / test / holdout_domain / fresh)")
args = parser.parse_args()

rules, taxonomy = B.read(args.rules), B.read(args.taxonomy)
rows = {r["id"]: r for r in (json.loads(x) for x in Path(args.source).read_text(encoding="utf-8").splitlines() if x.strip())}
unknown = set(args.ids) - set(rows)
if unknown:
    raise SystemExit("ids not found: " + ", ".join(sorted(unknown)))
minimum = rules.get("assert_min_args", {})


def guess_target(args_nodes):
    for arg in args_nodes:
        for part in ast.walk(arg):
            if isinstance(part, ast.Subscript) and isinstance(part.slice, ast.Constant) and isinstance(part.slice.value, str):
                return part.slice.value
    for arg in args_nodes:
        if isinstance(arg, ast.Name):
            return arg.id
    return ""


def draft_oracle(row):
    tree = ast.parse(row["target"])
    methods = B.class_methods(B.main_class(tree, rules))
    tests = [m for name, m in methods.items() if name.startswith("test")]
    api_text = row["inputs"]["api"]
    must_call, expect = [], []
    for method in tests:
        for name in B.call_names(method):
            if name not in must_call and re.search(r"\b" + re.escape(name) + r"\b", api_text):
                must_call.append(name)
        for call, call_args in B.assertion_calls(method, minimum):
            target = guess_target(call_args)
            for value in B.constants(call_args):
                kind = "assert_contains" if call.func.attr in ("assertIn", "assertNotIn") and isinstance(value, str) else "assert_value"
                item = {"kind": kind, "target": target, "value": value}
                if item not in expect:
                    expect.append(item)
    cleanup = sorted(n for n in B.teardown_calls(tree, rules) if re.search(r"\b" + re.escape(n) + r"\b", api_text))
    first = row["inputs"]["scenario"].strip().splitlines()[0] if row["inputs"]["scenario"].strip() else ""
    return {"status": "draft",
            "target_branch": re.sub(r"^测试分支[:：]\s*", "", first),
            "evidence": "scenario",
            "must_call": must_call, "expect": expect, "cleanup_required": cleanup, "must_not_call": [],
            "notes": "DRAFT generated from gold.py by import_pool.py. Keep only what the scenario states: "
                     "must_call = interfaces the scenario requires, expect = the expected outputs the scenario writes down "
                     "(normal flow: success code and the stated side effects; exception flow: the contracted error code "
                     "and message). Remove test-data values the scenario does not prescribe."}


pool = Path(args.pool)
for task_id in args.ids:
    row = rows[task_id]
    target = pool / task_id
    if target.exists():
        raise SystemExit("%s already exists; edit it in place or choose another id" % target)
    tags = {key: (row.get("tags") or {}).get(key, "") for key in taxonomy["dimensions"]}
    split = args.split or (row.get("split") if row.get("split") in taxonomy["splits"] else "dev")
    target.mkdir(parents=True)
    B.write(target / "task.json", {"instance_id": task_id, "split": split, "source_group": row["source_group"],
                                   "tags": tags, "inputs": row["inputs"]})
    (target / "gold.py").write_text(row["target"], encoding="utf-8")
    B.write(target / "oracle.json", draft_oracle(row))
    B.write(target / "provenance.json", {"origin": row.get("origin"), "sources": row.get("provenance", []),
                                         "candidate_file": str(args.source), "candidate_sha256": B.sha(args.source),
                                         "build_notes": row.get("build_notes"), "review_status": "pending",
                                         "reviewer": "", "reviewed_at": "", "review_notes": ""})
    print("created %s (split=%s); now review task.json tags, oracle.json, provenance.json" % (target, split))
print("Remember: do not copy these ids into data/private/train/.")
