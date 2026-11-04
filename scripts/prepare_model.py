"""Downloads only the public starter model; run before accessing internal data."""
import argparse
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
from common import read, write

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="configs/cpu-smoke.json")
args = parser.parse_args()
config = read(args.config)
lock_path = Path(config["model_lock"])
if lock_path.exists():
    raise SystemExit("model lock exists; reuse it, or choose a different lock path for a new model version")
model_id = config["model_id"]
revision = HfApi().model_info(model_id).sha
local = Path(snapshot_download(model_id, revision=revision, cache_dir="models/cache",
                              allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "LICENSE*"])).resolve()
write(lock_path, {"model_id": model_id, "revision": revision, "local_path": str(local)})
print("Pinned model revision:", revision)
print("Saved lock:", lock_path)
