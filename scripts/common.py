"""Standard-library utilities; contains no model or network access."""
import ast
import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


INPUT_FIELDS = ("rules", "scenario", "api", "framework", "reference")


def data_paths(value):
    """A config's "data" may be one path or a list of batch files forming the training pool."""
    paths = [value] if isinstance(value, (str, Path)) else list(value)
    if not paths:
        raise ValueError("no data files")
    return [Path(p) for p in paths]


def normalized_target_digest(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()


def load_data(path, required_splits=("train",)):
    """Validate one or more JSONL files as a single dataset.

    The training pool normally holds only split=train; evaluation tasks live in the benchmark
    suite. required_splits lets callers that still keep dev/test in one file insist on them.
    """
    rows = []
    for file in data_paths(path):
        rows += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("empty dataset")
    ids, groups, targets = set(), {}, {}
    for row in rows:
        for name in ("id", "source_group", "origin", "target"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError("missing or blank field: " + name)
        if row["id"] in ids:
            raise ValueError("duplicate id: " + row["id"])
        ids.add(row["id"])
        if row.get("split") not in {"train", "dev", "test"}:
            raise ValueError("invalid split")
        if row["origin"] not in {"original", "reconstructed", "synthetic"}:
            raise ValueError("invalid origin")
        if row.get("review_status") != "approved":
            raise ValueError("sample is not approved: " + row["id"])
        if (not isinstance(row.get("provenance"), list) or not row["provenance"]
                or not all(isinstance(x, str) and x.strip() for x in row["provenance"])):
            raise ValueError("missing provenance")
        for name in INPUT_FIELDS:
            if not isinstance(row.get("inputs", {}).get(name), str) or not row["inputs"][name].strip():
                raise ValueError("missing input: " + name)
        previous = groups.setdefault(row["source_group"], row["split"])
        if previous != row["split"]:
            raise ValueError("source group crosses splits: " + row["source_group"])
        previous = targets.setdefault(normalized_target_digest(row["target"]), row["split"])
        if previous != row["split"]:
            raise ValueError("identical target crosses splits")
        ast.parse(row["target"])
    missing = set(required_splits) - {r["split"] for r in rows}
    if missing:
        raise ValueError("dataset lacks required splits: " + ", ".join(sorted(missing)))
    return rows


def identities(text, attrs=("script_id",)):
    """Values such as script_id = "..." found anywhere in a script or a block of reference text."""
    found = set()
    for attr in attrs:
        found |= set(re.findall(r"\b" + re.escape(attr) + r"\s*=\s*[\"']([^\"']+)[\"']", text))
    return found


def check_benchmark_exclusion(rows, manifests):
    """Refuse to train on anything a frozen benchmark suite has reserved for evaluation."""
    problems = []
    for manifest_path in ([manifests] if isinstance(manifests, (str, Path)) else manifests):
        manifest = read(manifest_path)
        groups = set(manifest["source_groups"])
        digests = set(manifest["gold_digests"])
        ids = set(manifest.get("gold_identities", []))
        for row in rows:
            if row["split"] != "train":
                continue
            if row["source_group"] in groups:
                problems.append("%s: source_group %s is reserved by %s" % (row["id"], row["source_group"], manifest["suite"]))
            if normalized_target_digest(row["target"]) in digests:
                problems.append("%s: target equals a benchmark gold answer in %s" % (row["id"], manifest["suite"]))
            shared = identities(row["target"]) & ids
            if shared:
                problems.append("%s: target shares identity %s with %s" % (row["id"], sorted(shared), manifest["suite"]))
            shared = identities(row["inputs"]["reference"]) & ids
            if shared:
                problems.append("%s: reference contains benchmark gold identity %s" % (row["id"], sorted(shared)))
    if problems:
        raise ValueError("training data overlaps the benchmark:\n  " + "\n  ".join(problems))


def messages(row):
    labels = {"rules": "业务规则", "scenario": "测试剧本", "api": "可用 API",
              "framework": "框架约定", "reference": "参考脚本"}
    content = "\n\n".join(labels[key] + "\n" + row["inputs"][key] for key in labels)
    return [{"role": "system", "content": "根据提供的资料编写 Python unittest 测试。只输出完整 Python 文件，不输出 Markdown 围栏。"},
            {"role": "user", "content": content}]


def encode_sample(tokenizer, row, max_length):
    prompt = tokenizer.apply_chat_template(messages(row), tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages(row) + [{"role": "assistant", "content": row["target"]}],
                                        tokenize=True, add_generation_prompt=False)
    if full[:len(prompt)] != prompt:
        raise ValueError("chat template prefix mismatch: " + row["id"])
    if len(full) > max_length:
        raise ValueError(f"sample {row['id']} has {len(full)} tokens, exceeds {max_length}; no silent truncation")
    if len(full) <= len(prompt):
        raise ValueError("no supervised tokens")
    return {"input_ids": full, "attention_mask": [1] * len(full),
            "labels": [-100] * len(prompt) + full[len(prompt):]}


def capture_env():
    result = {"python": sys.version, "platform": platform.platform(), "processor": platform.processor()}
    for key, command in (("packages", [sys.executable, "-m", "pip", "freeze"]),
                         ("commit", ["git", "rev-parse", "HEAD"]),
                         ("working_tree", ["git", "status", "--short"])):
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result[key] = process.stdout.strip() if process.returncode == 0 else "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            result[key] = "unavailable"
    return result
