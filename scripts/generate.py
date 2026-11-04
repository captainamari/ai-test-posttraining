"""Generate baseline or adapter candidates; never executes generated Python.

generate.py           quick look at rows of a training-format JSONL (e.g. a split of the toy data)
bench/run_generate.py benchmark runs; both share generate_items() so settings stay identical
"""
import argparse
import os
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from common import capture_env, data_paths, load_data, messages, read, sha, write


def load_model(config, adapter):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
    lock = read(config["model_lock"])
    if lock["model_id"] != config["model_id"]:
        raise ValueError("model lock mismatch")
    set_seed(config["seed"])
    torch.set_num_threads(config["threads"])
    tokenizer = AutoTokenizer.from_pretrained(lock["local_path"], local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(lock["local_path"], local_files_only=True, torch_dtype=torch.float32,
                                                 attn_implementation=config.get("attn_implementation", "eager"))
    if adapter:
        from peft import PeftModel
        trained_lock = read(Path(adapter) / "model-lock.json")
        if (trained_lock["model_id"], trained_lock["revision"]) != (lock["model_id"], lock["revision"]):
            raise ValueError("adapter and baseline model revisions differ")
        model = PeftModel.from_pretrained(model, str(Path(adapter) / "adapter"), local_files_only=True)
    model.eval()
    model.config.use_cache = True
    return tokenizer, model, lock


def generate_items(config, adapter, items, max_new_tokens, out, file_for, extra_settings=None):
    """items: dicts with "id" and "inputs". Writes raw outputs, records.json, settings.json, status.json."""
    import torch
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write(out / "status.json", {"status": "started"})
    tokenizer, model, lock = load_model(config, adapter)
    generation = dict(config.get("generation", {}))
    write(out / "environment.json", capture_env())
    write(out / "settings.json", {"config": config, "model_lock": lock, "adapter_run": str(adapter) if adapter else None,
                                   "do_sample": False, "max_new_tokens": max_new_tokens, "generation": generation,
                                   **(extra_settings or {})})
    records = []
    for index, item in enumerate(items):
        ids = tokenizer.apply_chat_template(messages(item), tokenize=True, add_generation_prompt=True, return_tensors="pt")
        if ids.shape[1] > config["max_length"]:
            raise ValueError("prompt of %s exceeds max_length; inspect inputs rather than silently truncating" % item["id"])
        started = time.perf_counter()
        with torch.inference_mode():
            result = model.generate(ids, attention_mask=torch.ones_like(ids), do_sample=False,
                                    max_new_tokens=max_new_tokens, pad_token_id=tokenizer.eos_token_id, **generation)
        generated = result[0, ids.shape[1]:]
        file = file_for(index, item)
        (out / file).parent.mkdir(parents=True, exist_ok=True)
        (out / file).write_text(tokenizer.decode(generated, skip_special_tokens=True), encoding="utf-8")
        eos = model.generation_config.eos_token_id
        eos_ids = eos if isinstance(eos, list) else [eos]
        records.append({"id": item["id"], "file": file, "input_tokens": ids.shape[1], "output_tokens": len(generated),
                        "seconds": time.perf_counter() - started,
                        "hit_token_limit": len(generated) >= max_new_tokens and int(generated[-1]) not in eos_ids})
        write(out / "records.json", records)
        print("generated %d/%d %s in %.0fs" % (index + 1, len(items), item["id"], records[-1]["seconds"]), flush=True)
    write(out / "status.json", {"status": "generation_completed", "count": len(records), "quality_verdict": "not_evaluated"})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/cpu-smoke.json")
    parser.add_argument("--adapter", help="Training run directory, NOT its adapter subdirectory")
    parser.add_argument("--split", choices=["train", "dev", "test"], default="dev")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    config = read(args.config)
    rows = [r for r in load_data(config["data"], required_splits=()) if r["split"] == args.split]
    if not rows:
        raise SystemExit("no rows with split=%s in %s" % (args.split, config["data"]))
    generate_items(config, args.adapter, rows, args.max_new_tokens, args.out, lambda i, _: f"candidate-{i:04d}.txt",
                   {"split": args.split, "data": [{"path": str(p), "sha256": sha(p)} for p in data_paths(config["data"])]})


if __name__ == "__main__":
    main()
