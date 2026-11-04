"""Shared benchmark logic: instance format, validation, static and oracle scoring.

Nothing here executes candidate or gold code; everything is AST and text analysis.
"""
import ast
import builtins
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import INPUT_FIELDS, identities, normalized_target_digest, read, sha, write  # noqa: E402

SCORER_VERSION = "0.1"
REQUIRED_FILES = ("task.json", "gold.py", "oracle.json", "provenance.json")
EXPECT_KINDS = ("assert_value", "assert_contains")
SAFE_STDLIB = ["json", "re", "time", "datetime", "uuid", "random", "string", "math", "copy", "collections",
               "itertools", "typing", "decimal", "base64", "hashlib", "hmac", "unittest", "logging", "threading"]
FENCE = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\n(.*?)```", re.S)
TITLE = re.compile(r"class\s+\w+\s*\([^)]*\)\s*:\s*\n\s*(?:\"\"\"|''')\s*\n?\s*([^\n]+)")


# ----------------------------------------------------------------------------- instances

def load_instance(directory):
    directory = Path(directory)
    missing = [f for f in REQUIRED_FILES if not (directory / f).is_file()]
    if missing:
        raise ValueError("%s: missing %s" % (directory.name, ", ".join(missing)))
    return {"dir": directory, "task": read(directory / "task.json"), "oracle": read(directory / "oracle.json"),
            "provenance": read(directory / "provenance.json"),
            "gold": (directory / "gold.py").read_text(encoding="utf-8")}


def instance_dirs(root):
    return sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith("."))


def validate_instance(inst, rules, taxonomy, for_freeze=True):
    """Return a list of problems; empty means the instance may enter a frozen suite."""
    errors = []
    task, oracle, prov = inst["task"], inst["oracle"], inst["provenance"]
    name = inst["dir"].name
    if task.get("instance_id") != name:
        errors.append("task.instance_id must equal directory name %s" % name)
    if task.get("split") not in taxonomy["splits"]:
        errors.append("split must be one of %s" % taxonomy["splits"])
    if not isinstance(task.get("source_group"), str) or not task["source_group"].strip():
        errors.append("source_group is empty")
    for field in INPUT_FIELDS:
        if not isinstance(task.get("inputs", {}).get(field), str) or not task["inputs"][field].strip():
            errors.append("inputs.%s is empty" % field)
    tags = task.get("tags", {})
    for key in tags:
        if key not in taxonomy["dimensions"]:
            errors.append("unknown tag %s (add it to taxonomy first)" % key)
    for key, spec in taxonomy["dimensions"].items():
        value = tags.get(key)
        if not value:
            if spec.get("required"):
                errors.append("tag %s is required" % key)
        elif spec.get("values") and value not in spec["values"]:
            errors.append("tag %s=%s not in %s" % (key, value, spec["values"]))
    try:
        ast.parse(inst["gold"])
    except SyntaxError as error:
        errors.append("gold.py syntax error: %s" % error)
        return errors
    if oracle.get("status") not in ("draft", "approved"):
        errors.append("oracle.status must be draft or approved")
    elif for_freeze and oracle["status"] != "approved":
        errors.append("oracle.status is still draft")
    if not str(oracle.get("target_branch", "")).strip():
        errors.append("oracle.target_branch is empty")
    if oracle.get("evidence") not in ("rules", "scenario"):
        errors.append("oracle.evidence must be rules or scenario")
    for key in ("must_call", "expect", "cleanup_required", "must_not_call"):
        if not isinstance(oracle.get(key, []), list):
            errors.append("oracle.%s must be a list" % key)
    if for_freeze and not oracle.get("must_call"):
        errors.append("oracle.must_call is empty")
    if for_freeze and not oracle.get("expect"):
        errors.append("oracle.expect is empty")
    for index, item in enumerate(oracle.get("expect", [])):
        if not isinstance(item, dict) or item.get("kind") not in EXPECT_KINDS or item.get("value") in (None, ""):
            errors.append("oracle.expect[%d] needs kind in %s and a value" % (index, EXPECT_KINDS))
    text = "\n".join(str(v) for v in task.get("inputs", {}).values())
    for call in oracle.get("must_call", []):
        if not re.search(r"\b" + re.escape(call.split(".")[-1]) + r"\b", text):
            errors.append("must_call %s does not appear in inputs: the model could not know it" % call)
    if for_freeze:
        if prov.get("review_status") != "approved":
            errors.append("provenance.review_status is not approved")
        if not str(prov.get("reviewer", "")).strip():
            errors.append("provenance.reviewer is empty")
        if not prov.get("sources"):
            errors.append("provenance.sources is empty")
    if not errors:
        result = score_candidate(inst["gold"], False, inst, rules)
        if not result["auto_pass"]:
            errors.append("gold answer fails its own checks (calibration): " + "; ".join(failure_reasons(result)))
    return errors


# ----------------------------------------------------------------------------- suites

def write_readonly(path):
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def json_line(value):
    return json.dumps(value, ensure_ascii=False, default=str) + "\n"


def copy_instance(source, target):
    shutil.copytree(source, target)
    for path in Path(target).rglob("*"):
        if path.is_file():
            write_readonly(path)


def verify_suite(suite_dir):
    """Check every frozen file against manifest.json; return the manifest."""
    suite_dir = Path(suite_dir)
    manifest = read(suite_dir / "manifest.json")
    bad = []
    for name, digest in manifest["files"].items():
        if sha(suite_dir / name) != digest:
            bad.append(name)
    for inst in manifest["instances"]:
        for name, digest in inst["files"].items():
            path = suite_dir / "instances" / inst["id"] / name
            if not path.is_file() or sha(path) != digest:
                bad.append("instances/%s/%s" % (inst["id"], name))
    if bad:
        raise ValueError("suite %s was modified after freezing: %s" % (suite_dir, ", ".join(bad)))
    return manifest


def suite_rules(suite_dir):
    return read(Path(suite_dir) / "rules.json")


def suite_instances(suite_dir, splits=None):
    manifest = verify_suite(suite_dir)
    chosen = [i for i in manifest["instances"] if not splits or i["split"] in splits]
    return manifest, [load_instance(Path(suite_dir) / "instances" / i["id"]) for i in chosen]


# ----------------------------------------------------------------------------- static analysis helpers

def extract(raw):
    """Return (code, number_of_fenced_blocks). Analysis uses the first block; raw output stays untouched."""
    blocks = FENCE.findall(raw)
    if blocks:
        return blocks[0], len(blocks)
    if raw.lstrip().startswith("```"):  # opened but never closed: truncated output
        return raw.lstrip().split("\n", 1)[-1], 1
    return raw, 0


def name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def base_allowances(tree, rules):
    allowed = set(dir(builtins)) | set(dir(unittest.TestCase)) | set(rules.get("allowed_names", []))
    for kind in (dict, list, str, set, tuple, bytes, int, float):
        allowed |= set(dir(kind))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            allowed.add(node.name)
        elif isinstance(node, ast.Import):
            modules = [(a.name, None) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [(node.module, a.name) for a in node.names]
        else:
            continue
        for module, member in modules:
            if module in SAFE_STDLIB:  # only import known-harmless standard modules
                try:
                    loaded = importlib.import_module(module)
                    allowed |= set(dir(loaded))
                    if member and hasattr(loaded, member):
                        allowed |= set(dir(getattr(loaded, member)))
                except Exception:
                    pass
    return allowed


def call_names(tree, allowed=frozenset()):
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = name_of(node.func)
            if name and name not in allowed:
                names.setdefault(name, []).append(node)
    return names


def assertion_calls(tree, minimum):
    """(call, arguments excluding the trailing message slot) for each configured assertion."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in minimum:
            yield node, node.args[:minimum[node.func.attr] - 1]


def constants(nodes):
    for arg in nodes:
        for part in ast.walk(arg):
            if isinstance(part, ast.Constant) and part.value is not None and not isinstance(part.value, bool):
                yield part.value


def assertion_literals(tree, minimum):
    return {repr(value) for _, args in assertion_calls(tree, minimum) for value in constants(args)}


def is_super_call(stmt, method):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr == method
            and isinstance(stmt.value.func.value, ast.Call) and name_of(stmt.value.func.value.func) == "super")


def main_class(tree, rules):
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    base = rules.get("base_class")
    owners = [c for c in classes if any(name_of(b) == base for b in c.bases)] if base else classes
    return owners[0] if owners else None


def class_methods(cls):
    return {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if cls else {}


def framework_checks(tree, rules):
    checks = {}
    cls = main_class(tree, rules)
    if rules.get("base_class"):
        checks["base_class"] = cls is not None
    if cls is None:
        return checks, 0
    methods = class_methods(cls)
    attrs = {t.id for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    attrs |= {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    for attr in rules.get("required_class_attrs", []):
        checks["attr:" + attr] = attr in attrs
    for method in rules.get("required_methods", []):
        checks["method:" + method] = method in methods
    tests = [n for n in methods if n.startswith("test")]
    limits = rules.get("test_method_count", {})
    if "min" in limits:
        checks["tests>=%d" % limits["min"]] = len(tests) >= limits["min"]
    if "max" in limits:
        checks["tests<=%d" % limits["max"]] = len(tests) <= limits["max"]
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported |= {node.module + "." + a.name for a in node.names}
    for item in rules.get("required_imports", []):
        checks["import:" + item] = item in imported
    for method, where in rules.get("super_calls", {}).items():
        body = methods[method].body if method in methods else []
        if where == "last":
            checks["super:%s:last" % method] = bool(body) and is_super_call(body[-1], method)
        else:
            checks["super:%s" % method] = any(is_super_call(s, method) for stmt in body for s in ast.walk(stmt))
    called = {dotted(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for item in rules.get("forbidden_calls", []):
        checks["forbid:" + item] = item not in called
    minimum = rules.get("assert_min_args", {})
    if rules.get("require_assert_message") and minimum:
        bad = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in minimum and len(n.args) + sum(k.arg == "msg" for k in n.keywords) < minimum[n.func.attr]]
        checks["assert_messages"] = not bad
    markers = rules.get("test_docstring_markers_any")
    if markers and tests:
        doc = ast.get_docstring(methods[tests[0]]) or ""
        checks["test_docstring_marker"] = any(m in doc for m in markers)
    return checks, len(tests)


def class_title(tree, rules):
    cls = main_class(tree, rules)
    doc = ast.get_docstring(cls) if cls else None
    return doc.strip().splitlines()[0].strip() if doc and doc.strip() else None


def teardown_calls(tree, rules):
    """Names called in tearDown, following one level of self.<helper>() calls."""
    methods = class_methods(main_class(tree, rules))
    if "tearDown" not in methods:
        return set()
    names = set(call_names(methods["tearDown"]))
    for node in ast.walk(methods["tearDown"]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self" and node.func.attr in methods and node.func.attr != "tearDown"):
            names |= set(call_names(methods[node.func.attr]))
    return names


def match_expect(tree, item, minimum):
    """'full' when an assertion contains the value and mentions the target, 'value_only', or 'miss'."""
    value, target = item["value"], str(item.get("target", "") or "")
    best = "miss"
    for _, args in assertion_calls(tree, minimum):
        values = list(constants(args))
        if item["kind"] == "assert_value":
            hit = any(type(v) is type(value) and v == value for v in values)
        else:
            hit = any(isinstance(v, str) and str(value) in v for v in values)
        if not hit:
            continue
        if not target or any(target in ast.unparse(arg) for arg in args):
            return "full"
        best = "value_only"
    return best


# ----------------------------------------------------------------------------- scoring

def score_candidate(raw, truncated, inst, rules):
    task, oracle, gold = inst["task"], inst["oracle"], inst["gold"]
    minimum = rules.get("assert_min_args", {})
    attrs = tuple(rules.get("identity_attrs", ["script_id"]))
    gold_tree = ast.parse(gold)
    gold_calls = set(call_names(gold_tree, base_allowances(gold_tree, rules)))
    gold_literals = assertion_literals(gold_tree, minimum)
    code, blocks = extract(raw)
    result = {"artifact_sha": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "missing": False,
              "fence_free": "```" not in raw, "not_truncated": not truncated, "single_block": blocks <= 1,
              "syntax_ok": False, "framework_ok": False, "framework_failed": [], "soft_failed": [], "discovered": 0,
              "shadows_api": [], "ungrounded_calls": [], "ungrounded_kwargs": [], "copied_identity": [],
              "static_pass": False,
              "must_call_missing": list(oracle.get("must_call", [])),
              "expect": [{"index": i, "kind": e["kind"], "target": e.get("target", ""), "value": e["value"], "hit": "miss"}
                         for i, e in enumerate(oracle.get("expect", []))],
              "cleanup_missing": list(oracle.get("cleanup_required", [])), "forbidden_called": [],
              "must_call_total": len(oracle.get("must_call", [])), "cleanup_total": len(oracle.get("cleanup_required", [])),
              "oracle_pass": False, "auto_pass": False,
              "gold_calls": sorted(gold_calls), "missing_calls": sorted(gold_calls),
              "gold_literals": sorted(gold_literals), "missing_literals": sorted(gold_literals), "assert_count": 0}
    try:
        tree = ast.parse(code)
        result["syntax_ok"] = bool(code.strip())
    except SyntaxError:
        return result
    if not result["syntax_ok"]:
        return result
    inputs_text = "\n".join(task["inputs"].values())
    known = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", inputs_text))
    checks, discovered = framework_checks(tree, rules)
    soft = set(rules.get("soft_checks", []))
    result["framework_failed"] = sorted(k for k, ok in checks.items() if not ok and k not in soft)
    result["soft_failed"] = sorted(k for k, ok in checks.items() if not ok and k in soft)
    result["framework_ok"] = not result["framework_failed"]
    result["discovered"] = discovered
    calls = call_names(tree, base_allowances(tree, rules))
    result["ungrounded_calls"] = sorted(n for n in calls if n not in known)
    result["ungrounded_kwargs"] = sorted({n + "(" + k.arg + "=)" for n, nodes in calls.items() if n in known
                                          for node in nodes for k in node.keywords if k.arg and k.arg not in known})
    result["shadows_api"] = sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef)
                                   and re.search(r"\b" + re.escape(n.name) + r"\b", task["inputs"]["api"]))
    if rules.get("forbid_reference_identity", True):
        reference = task["inputs"]["reference"]
        copied = sorted(identities(code, attrs) & identities(reference, attrs))
        title = class_title(tree, rules)
        if title and title in set(TITLE.findall(reference)) and title != class_title(gold_tree, rules):
            copied.append("title:" + title)
        result["copied_identity"] = copied
    result["static_pass"] = all((result["fence_free"], result["not_truncated"], result["single_block"],
                                 result["framework_ok"], discovered >= 1, not result["shadows_api"],
                                 not result["copied_identity"],
                                 not (rules.get("forbid_ungrounded_calls", True) and result["ungrounded_calls"])))
    local_defs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    all_called = set(call_names(tree)) - local_defs  # calling your own re-implementation is not calling the API
    result["must_call_missing"] = [c for c in oracle.get("must_call", []) if c.split(".")[-1] not in all_called]
    for item in result["expect"]:
        item["hit"] = match_expect(tree, item, minimum)
    cleanup = teardown_calls(tree, rules)
    result["cleanup_missing"] = [c for c in oracle.get("cleanup_required", []) if c.split(".")[-1] not in cleanup]
    result["forbidden_called"] = [c for c in oracle.get("must_not_call", []) if c.split(".")[-1] in all_called]
    result["oracle_pass"] = (not result["must_call_missing"] and all(e["hit"] == "full" for e in result["expect"])
                             and not result["cleanup_missing"] and not result["forbidden_called"])
    result["auto_pass"] = result["static_pass"] and result["oracle_pass"]
    literals = assertion_literals(tree, minimum)
    result["missing_calls"] = sorted(gold_calls - set(calls))
    result["missing_literals"] = sorted(gold_literals - literals)
    result["assert_count"] = sum(1 for _ in assertion_calls(tree, minimum))
    return result


def missing_result(inst, rules):
    result = score_candidate("", True, inst, rules)
    result.update(missing=True, fence_free=False, single_block=False)
    return result


def failure_reasons(result):
    reasons = []
    if result.get("missing"):
        return ["not generated"]
    for key, label in (("fence_free", "markdown fence"), ("not_truncated", "truncated"),
                       ("single_block", "several code blocks"), ("syntax_ok", "syntax error")):
        if not result[key]:
            reasons.append(label)
    if result["syntax_ok"]:
        reasons += ["framework:" + x for x in result["framework_failed"]]
        if result["discovered"] < 1:
            reasons.append("no test method")
        reasons += ["redefines API:" + x for x in result["shadows_api"]]
        reasons += ["copied reference identity:" + x for x in result["copied_identity"]]
        reasons += ["ungrounded call:" + x for x in result["ungrounded_calls"]]
        reasons += ["must_call missing:" + x for x in result["must_call_missing"]]
        reasons += ["expect %s=%r %s" % (e["target"], e["value"], e["hit"]) for e in result["expect"] if e["hit"] != "full"]
        reasons += ["cleanup missing:" + x for x in result["cleanup_missing"]]
        reasons += ["forbidden call:" + x for x in result["forbidden_called"]]
    return reasons


# ----------------------------------------------------------------------------- summaries

REVIEW_COLUMNS = ["instance_id", "executed", "run_status", "environment_error", "review_verdict",
                  "follows_scenario", "invented_api", "repair_minutes", "notes"]


def metric_rows(results, reviews=None):
    """(label, numerator, denominator) in report order. results: per-instance records with a "result" key."""
    n = len(results)
    r = [x["result"] for x in results]
    count = lambda f: sum(1 for x in r if f(x))
    total = lambda f: sum(f(x) for x in r)
    rows = [("generated", count(lambda x: not x["missing"]), n),
            ("L0 not truncated", count(lambda x: x["not_truncated"]), n),
            ("L0 no markdown fence", count(lambda x: x["fence_free"]), n),
            ("L0 syntax ok", count(lambda x: x["syntax_ok"]), n),
            ("L1 framework ok", count(lambda x: x["framework_ok"]), n),
            ("L2 no copied reference identity", count(lambda x: x["syntax_ok"] and not x["copied_identity"]), n),
            ("L2 no ungrounded calls", count(lambda x: x["syntax_ok"] and not x["ungrounded_calls"]), n),
            ("L2 static_pass", count(lambda x: x["static_pass"]), n),
            ("L2.5 must_call hit", total(lambda x: x["must_call_total"] - len(x["must_call_missing"])),
             total(lambda x: x["must_call_total"])),
            ("L2.5 expect full", total(lambda x: sum(e["hit"] == "full" for e in x["expect"])), total(lambda x: len(x["expect"]))),
            ("L2.5 expect value_only", total(lambda x: sum(e["hit"] == "value_only" for e in x["expect"])),
             total(lambda x: len(x["expect"]))),
            ("L2.5 cleanup hit", total(lambda x: x["cleanup_total"] - len(x["cleanup_missing"])),
             total(lambda x: x["cleanup_total"])),
            ("L2.5 oracle_pass", count(lambda x: x["oracle_pass"]), n),
            ("AUTO auto_pass", count(lambda x: x["auto_pass"]), n),
            ("sim gold api calls", total(lambda x: len(x["gold_calls"]) - len(x["missing_calls"])),
             total(lambda x: len(x["gold_calls"]))),
            ("sim gold assertion literals", total(lambda x: len(x["gold_literals"]) - len(x["missing_literals"])),
             total(lambda x: len(x["gold_literals"])))]
    mine = [reviews[x["id"]] for x in results if x["id"] in (reviews or {})]
    if any(str(v.get(k) or "").strip() for v in mine for k in REVIEW_COLUMNS[1:]):
        filled = lambda key: [v for v in mine if str(v.get(key, "")).strip()]
        yes = lambda key, word="yes": sum(v[key].strip().lower() == word for v in filled(key))
        num = lambda key: sum(float(v[key]) for v in filled(key))
        rows += [("L3 executed", yes("executed"), n),
                 ("L3 run pass", yes("run_status", "pass"), n),
                 ("L3 environment errors", yes("environment_error"), n),
                 ("L4 accepted without change", yes("review_verdict", "accept"), n),
                 ("L4 follows scenario", yes("follows_scenario"), n),
                 ("L4 invented API", yes("invented_api"), n),
                 ("L4 repair minutes (sum / reviewed)", num("repair_minutes"), len(filled("repair_minutes")))]
    return rows


def read_reviews(run_dir):
    import csv
    path = Path(run_dir) / "review.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["instance_id"]: row for row in csv.DictReader(stream) if row.get("instance_id")}


# ----------------------------------------------------------------------------- leakage helpers

LITERAL = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|\d+(?:\.\d+)?")
TOKEN = re.compile(r"[A-Za-z_]\w*|[^\sA-Za-z_]")


def shingles(text, size=5):
    """Code fingerprint that ignores literal values, comments and layout (same template, other parameters -> similar)."""
    text = re.sub(r"#[^\n]*", " ", text)
    text = LITERAL.sub(" L ", text)
    tokens = TOKEN.findall(text)
    return {tuple(tokens[i:i + size]) for i in range(max(len(tokens) - size + 1, 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def containment(part, whole):
    return len(part & whole) / len(part) if part else 0.0


__all__ = ["SCORER_VERSION", "load_instance", "instance_dirs", "validate_instance", "verify_suite", "suite_rules",
           "suite_instances", "copy_instance", "write_readonly", "score_candidate", "missing_result", "failure_reasons",
           "shingles", "jaccard", "containment", "identities", "normalized_target_digest", "read", "sha", "write",
           "call_names", "class_methods", "main_class", "assertion_calls", "constants", "teardown_calls",
           "metric_rows", "read_reviews", "REVIEW_COLUMNS"]
