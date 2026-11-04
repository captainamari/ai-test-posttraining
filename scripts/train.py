"""CPU FP32 LoRA training on the split=train rows of the training pool."""
import argparse
import json
import os
import time
import traceback
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from common import (capture_env, check_benchmark_exclusion, data_paths, encode_sample, load_data, read, sha,
                    write)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/cpu-smoke.json")
    parser.add_argument("--run", required=True)
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args()
    config = read(args.config)
    if args.max_steps is not None:
        config["max_steps"] = args.max_steps
    if config["max_steps"] < 1:
        raise ValueError("max_steps must be positive")
    run = Path(args.run)
    exclusions = config.get("exclude_manifests", [])
    run.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write(run / "status.json", {"status": "started"})
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, TrainerCallback, set_seed
        from peft import LoraConfig, get_peft_model

        torch.set_num_threads(config["threads"])
        set_seed(config["seed"])
        lock = read(config["model_lock"])
        if lock["model_id"] != config["model_id"]:
            raise ValueError("config model differs from model lock")
        write(run / "config.json", config)
        write(run / "environment.json", capture_env())
        write(run / "model-lock.json", lock)
        write(run / "data-manifest.json", {"files": [{"path": str(p), "sha256": sha(p)} for p in data_paths(config["data"])],
                                           "benchmark_exclusions": [{"path": str(p), "sha256": sha(p)} for p in exclusions]})
        rows = load_data(config["data"])
        if exclusions:
            check_benchmark_exclusion(rows, exclusions)
        tokenizer = AutoTokenizer.from_pretrained(lock["local_path"], local_files_only=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        encoded = [encode_sample(tokenizer, row, config["max_length"]) for row in rows if row["split"] == "train"]
        write(run / "token-lengths.json", [{"input_tokens": len(x["input_ids"]),
                                           "supervised_tokens": sum(y != -100 for y in x["labels"])} for x in encoded])
        model = AutoModelForCausalLM.from_pretrained(lock["local_path"], local_files_only=True,
                                                    torch_dtype=torch.float32, attn_implementation=config.get("attn_implementation", "eager"))
        model.config.use_cache = False
        model = get_peft_model(model, LoraConfig(task_type="CAUSAL_LM", r=config["lora_r"],
                                                lora_alpha=config["lora_alpha"], lora_dropout=0.0,
                                                target_modules=config["target_modules"]))
        initial = {name: value.detach().cpu().clone() for name, value in model.named_parameters() if value.requires_grad}
        if not initial:
            raise ValueError("no trainable parameters")
        write(run / "parameters.json", {"trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
                                         "total": sum(p.numel() for p in model.parameters())})

        def collate(batch):
            width = max(len(x["input_ids"]) for x in batch)
            return {key: torch.tensor([x[key] + [pad] * (width - len(x[key])) for x in batch], dtype=torch.long)
                    for key, pad in (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}

        class Journal(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                with (run / "metrics.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"step": state.global_step, "elapsed_seconds": time.perf_counter() - started,
                                             **(logs or {})}, ensure_ascii=False) + "\n")

        training = TrainingArguments(output_dir=str(run / "checkpoints"), use_cpu=True, fp16=False, bf16=False,
                                     per_device_train_batch_size=1, gradient_accumulation_steps=config["gradient_accumulation_steps"],
                                     max_steps=config["max_steps"], learning_rate=config["learning_rate"],
                                     logging_steps=1, save_strategy="no", report_to="none", push_to_hub=False,
                                     dataloader_num_workers=0, dataloader_pin_memory=False, seed=config["seed"],
                                     optim="adamw_torch", label_names=["labels"],
                                     gradient_checkpointing=config.get("gradient_checkpointing", False),
                                     gradient_checkpointing_kwargs={"use_reentrant": False} if config.get("gradient_checkpointing") else None)
        trainer = Trainer(model=model, args=training, train_dataset=encoded, data_collator=collate,
                          callbacks=[Journal()])
        trainer.train()
        delta = max((value.detach().cpu() - initial[name]).abs().max().item()
                    for name, value in model.named_parameters() if name in initial)
        if not delta > 0:
            raise ValueError("adapter weights did not change")
        model.save_pretrained(run / "adapter", safe_serialization=True)
        tokenizer.save_pretrained(run / "adapter")
        trainer.save_state()
        write(run / "status.json", {"status": "training_completed", "steps": trainer.state.global_step,
                                     "train_samples": len(encoded), "epochs": trainer.state.global_step * config["gradient_accumulation_steps"] / len(encoded),
                                     "adapter_max_abs_change": delta, "elapsed_seconds": time.perf_counter() - started,
                                     "quality_verdict": "not_evaluated"})
    except Exception:
        (run / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        write(run / "status.json", {"status": "failed", "elapsed_seconds": time.perf_counter() - started})
        raise


if __name__ == "__main__":
    main()
