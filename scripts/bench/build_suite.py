"""Freeze reviewed pool instances into an immutable benchmark suite version.

Every instance must pass validation, including calibration (its gold answer must pass its own checks).
The suite directory gets copies of the rules and taxonomy, read-only files and a manifest with SHA256s.
"""
import argparse
import datetime
from collections import Counter
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("--pool", default="data/private/benchmark/pool")
parser.add_argument("--rules", default="data/private/benchmark/rules/framework-v0.1.json")
parser.add_argument("--taxonomy", default="data/private/benchmark/taxonomy.json")
parser.add_argument("--suites-root", default="data/private/benchmark/suites")
parser.add_argument("--version", required=True, help="e.g. v0.1")
parser.add_argument("--ids", nargs="*", help="only these pool instances (default: all)")
parser.add_argument("--only-ready", action="store_true", help="skip invalid instances instead of failing")
parser.add_argument("--note", default="", help="what changed compared with the previous version")
parser.add_argument("--check", action="store_true", help="validate and report only, do not write")
args = parser.parse_args()

rules, taxonomy = B.read(args.rules), B.read(args.taxonomy)
dirs = [d for d in B.instance_dirs(args.pool) if not args.ids or d.name in args.ids]
missing = set(args.ids or []) - {d.name for d in dirs}
if missing:
    raise SystemExit("not in pool: " + ", ".join(sorted(missing)))

ready, problems = [], {}
for directory in dirs:
    try:
        inst = B.load_instance(directory)
        errors = B.validate_instance(inst, rules, taxonomy, for_freeze=True)
    except Exception as error:  # unreadable JSON and similar
        inst, errors = None, ["cannot load: %s" % error]
    if errors:
        problems[directory.name] = errors
    else:
        ready.append(inst)

# Suite-level checks across instances.
groups, digests, owners = {}, {}, {}
for inst in ready:
    task = inst["task"]
    previous = groups.setdefault(task["source_group"], task["split"])
    if previous != task["split"]:
        problems.setdefault(task["instance_id"], []).append("source_group %s spans splits" % task["source_group"])
    digest = B.normalized_target_digest(inst["gold"])
    if digest in digests:
        problems.setdefault(task["instance_id"], []).append("gold identical to %s" % digests[digest])
    digests.setdefault(digest, task["instance_id"])
    for identity in B.identities(inst["gold"], tuple(rules.get("identity_attrs", ["script_id"]))):
        if identity in owners:
            problems.setdefault(task["instance_id"], []).append("identity %s also in %s" % (identity, owners[identity]))
        owners.setdefault(identity, task["instance_id"])
for inst in ready:
    leaked = B.identities(inst["task"]["inputs"]["reference"]) & set(owners)
    leaked -= B.identities(inst["gold"])
    if leaked:
        problems.setdefault(inst["task"]["instance_id"], []).append(
            "reference contains gold of other instances: %s" % ", ".join(owners[x] for x in sorted(leaked)))

for name, errors in sorted(problems.items()):
    print("[%s]" % name)
    for error in errors:
        print("  - " + error)
if problems and not args.only_ready:
    raise SystemExit("%d instance(s) not ready; fix them or use --only-ready" % len(problems))
ready = [i for i in ready if i["task"]["instance_id"] not in problems]
if not ready:
    raise SystemExit("no instance is ready")
print("ready: %d, skipped: %d" % (len(ready), len(problems)))
if args.check:
    raise SystemExit(0)

suite = Path(args.suites_root) / args.version
if suite.exists():
    raise SystemExit("%s exists; frozen versions are never modified, choose a new version" % suite)
(suite / "instances").mkdir(parents=True)
(suite / "rules.json").write_text(Path(args.rules).read_text(encoding="utf-8"), encoding="utf-8")
(suite / "taxonomy.json").write_text(Path(args.taxonomy).read_text(encoding="utf-8"), encoding="utf-8")
entries = []
for inst in sorted(ready, key=lambda i: i["task"]["instance_id"]):
    task = inst["task"]
    target = suite / "instances" / task["instance_id"]
    B.copy_instance(inst["dir"], target)
    files = {str(p.relative_to(target)): B.sha(p) for p in sorted(target.rglob("*")) if p.is_file()}
    entries.append({"id": task["instance_id"], "split": task["split"], "source_group": task["source_group"],
                    "tags": task.get("tags", {}), "files": files})
by_tag = {dim: dict(Counter(e["tags"].get(dim) or "(none)" for e in entries)) for dim in taxonomy["dimensions"]}
manifest = {"suite": args.version, "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": args.note, "scorer_version": B.SCORER_VERSION,
            "files": {"rules.json": B.sha(suite / "rules.json"), "taxonomy.json": B.sha(suite / "taxonomy.json")},
            "source_rules": str(args.rules), "source_taxonomy": str(args.taxonomy),
            "counts": {"instances": len(entries), "by_split": dict(Counter(e["split"] for e in entries)), "by_tag": by_tag,
                       "source_groups": len({e["source_group"] for e in entries})},
            "skipped": sorted(problems),
            "source_groups": sorted({e["source_group"] for e in entries}),
            "gold_digests": sorted(B.normalized_target_digest(i["gold"]) for i in ready),
            "gold_identities": sorted(x for x, owner in owners.items() if owner in {e["id"] for e in entries}),
            "instances": entries}
B.write(suite / "manifest.json", manifest)
for name in ("rules.json", "taxonomy.json", "manifest.json"):
    B.write_readonly(suite / name)
print("froze %s: %d instances, splits %s" % (suite, len(entries), manifest["counts"]["by_split"]))
print("next: python scripts/bench/check_leakage.py --suite %s --train <training pool files>" % suite)
