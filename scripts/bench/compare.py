"""Compare scored runs on the same frozen suite: layer metrics, tag slices, paired changes, per task.

  python scripts/bench/compare.py runs/bench/v0.1/E001-B0 runs/bench/v0.1/E001-B1 [--out report.md]

The first run is the baseline for the paired comparison. Uses each run's latest score directory.
Refuses to mix suites, rules or scorer versions.
"""
import argparse
from pathlib import Path

import benchlib as B

parser = argparse.ArgumentParser()
parser.add_argument("runs", nargs="+")
parser.add_argument("--metric", default="auto_pass", choices=["auto_pass", "static_pass", "oracle_pass"],
                    help="per-task pass/fail used for slices and paired comparison")
parser.add_argument("--out", help="write the markdown report here as well")
args = parser.parse_args()

loaded = []
for run in args.runs:
    scores = sorted((Path(run) / "scores").glob("*"))
    if not scores:
        raise SystemExit("%s has no scores; run score.py first" % run)
    summary = B.read(scores[-1] / "summary.json")
    results = [B.json.loads(line) for line in (scores[-1] / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    loaded.append({"run": run, "name": summary["settings"].get("run_id") or Path(run).name, "summary": summary,
                   "score_dir": scores[-1], "results": {r["id"]: r for r in results}, "reviews": B.read_reviews(run),
                   "settings": B.read(Path(run) / "settings.json")})
for key in ("manifest_sha256", "scorer_version", "rules_sha256"):
    if len({x["summary"][key] for x in loaded}) > 1:
        raise SystemExit("runs differ in %s; results are not comparable" % key)

common = sorted(set.intersection(*(set(x["results"]) for x in loaded)))
union = sorted(set.union(*(set(x["results"]) for x in loaded)))
lines = ["# Benchmark comparison", "",
         "suite `%s`, manifest `%s`, scorer v%s, metric `%s`" % (loaded[0]["summary"]["suite"],
                                                                 loaded[0]["summary"]["manifest_sha256"][:12],
                                                                 loaded[0]["summary"]["scorer_version"], args.metric), ""]
if common != union:
    lines += ["**Only %d of %d tasks are present in every run; tables below use the common tasks.**" % (len(common), len(union)), ""]
lines += ["| run | source | adapter / note | max_new_tokens | generation | scores |", "|---|---|---|---|---|---|"]
for x in loaded:
    s = x["settings"]
    lines.append("| %s | %s | %s | %s | %s | %s |" % (x["name"], s.get("source"), s.get("adapter_run") or s.get("note") or "-",
                                                     s.get("max_new_tokens", "-"), s.get("generation") or "-", x["score_dir"].name))

lines += ["", "## Layers", "", "| metric | " + " | ".join(x["name"] for x in loaded) + " |", "|---|" + "---|" * len(loaded)]
tables = [B.metric_rows([x["results"][t] for t in common], x["reviews"]) for x in loaded]
labels = list(dict.fromkeys(label for table in tables for label, _, _ in table))
for label in labels:
    cells = []
    for table in tables:
        found = [(n, d) for l, n, d in table if l == label]
        cells.append("%s/%s" % ((found[0][0] if isinstance(found[0][0], int) else round(found[0][0], 1)), found[0][1]) if found else "-")
    lines.append("| %s | %s |" % (label, " | ".join(cells)))

passed = lambda x, t: bool(x["results"][t]["result"][args.metric])
dimensions = sorted({k for x in loaded for t in common for k in x["results"][t]["tags"]} | {"split"})
lines += ["", "## By tag (%s)" % args.metric, "", "| tag | value | n | " + " | ".join(x["name"] for x in loaded) + " |",
          "|---|---|---|" + "---|" * len(loaded)]
for dim in dimensions:
    value_of = (lambda t, d=dim: loaded[0]["results"][t]["split"]) if dim == "split" else \
        (lambda t, d=dim: loaded[0]["results"][t]["tags"].get(d) or "(none)")
    for value in sorted({value_of(t) for t in common}):
        tasks = [t for t in common if value_of(t) == value]
        lines.append("| %s | %s | %d | %s |" % (dim, value, len(tasks), " | ".join(str(sum(passed(x, t) for t in tasks)) for x in loaded)))

if len(loaded) > 1:
    base = loaded[0]
    lines += ["", "## Paired against %s (%s)" % (base["name"], args.metric), "",
              "| run | improved | regressed | both pass | both fail |", "|---|---|---|---|---|"]
    details = []
    for x in loaded[1:]:
        up = [t for t in common if not passed(base, t) and passed(x, t)]
        down = [t for t in common if passed(base, t) and not passed(x, t)]
        lines.append("| %s | %d | %d | %d | %d |" % (x["name"], len(up), len(down),
                                                     sum(passed(base, t) and passed(x, t) for t in common),
                                                     sum(not passed(base, t) and not passed(x, t) for t in common)))
        details.append("- %s improved: %s; regressed: %s" % (x["name"], ", ".join(up) or "none", ", ".join(down) or "none"))
    lines += [""] + details
    lines += ["", "With few tasks report the counts above, not percentages. A difference of one or two tasks is noise."]

lines += ["", "## Per task", "", "| task | split | " + " | ".join(x["name"] for x in loaded) + " |", "|---|---|" + "---|" * len(loaded)]
for t in common:
    cells = []
    for x in loaded:
        item = x["results"][t]
        cells.append(("PASS" if item["result"][args.metric] else "fail: " + "; ".join(item["reasons"][:3])).replace("|", "/"))
    lines.append("| %s | %s | %s |" % (t, loaded[0]["results"][t]["split"], " | ".join(cells)))

report = "\n".join(lines) + "\n"
print(report)
if args.out:
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8")
