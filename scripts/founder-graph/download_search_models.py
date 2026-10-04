"""Download only the pinned Sentence Transformers files used by local search."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from nebula.founder_graph_local_models import (  # noqa: E402
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    E5_BASE_MODEL_ID,
    E5_BASE_MODEL_REVISION,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    build_local_search_manifest,
)


ALLOW_PATTERNS = [
    "config.json",
    "modules.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "vocab.txt",
    "merges.txt",
]


def main() -> int:
    snapshots = {}
    for model_id, revision in (
        (EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION),
        (E5_BASE_MODEL_ID, E5_BASE_MODEL_REVISION),
        (RERANKER_MODEL_ID, RERANKER_MODEL_REVISION),
    ):
        snapshots[model_id] = Path(snapshot_download(
            repo_id=model_id,
            revision=revision,
            allow_patterns=ALLOW_PATTERNS,
        ))
    manifests = {
        profile: build_local_search_manifest(profile, snapshot_paths=snapshots)
        for profile in ("small", "base")
    }
    print(json.dumps({"model_manifests": manifests}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
