"""Pinned, offline-only multilingual Sentence Transformers for graph search."""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import platform
from threading import RLock
from typing import Any, Mapping, Sequence


EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
EMBEDDING_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_LICENSE = "MIT"
E5_BASE_MODEL_ID = "intfloat/multilingual-e5-base"
E5_BASE_MODEL_REVISION = "d13f1b27baf31030b7fd040960d60d909913633f"
E5_BASE_DIMENSIONS = 768
E5_BASE_LICENSE = "MIT"
RERANKER_MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
RERANKER_LICENSE = "Apache-2.0"
RERANKER_MAX_LENGTH = 512
DEFAULT_EMBEDDING_PROFILE = "base"

_EMBEDDING_PROFILES = {
    "small": {
        "model_id": EMBEDDING_MODEL_ID,
        "revision": EMBEDDING_MODEL_REVISION,
        "dimensions": EMBEDDING_DIMENSIONS,
        "license": EMBEDDING_LICENSE,
    },
    "base": {
        "model_id": E5_BASE_MODEL_ID,
        "revision": E5_BASE_MODEL_REVISION,
        "dimensions": E5_BASE_DIMENSIONS,
        "license": E5_BASE_LICENSE,
    },
}
_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "vocab.txt",
    "merges.txt",
)


class LocalSearchModelUnavailable(RuntimeError):
    """The pinned local model dependency or files are unavailable."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_file_hashes(snapshot: Path | Mapping[str, Path]) -> tuple[str, dict[str, str]]:
    files = (
        dict(snapshot)
        if isinstance(snapshot, Mapping)
        else {
            name: snapshot / name
            for name in ("model.safetensors", *_TOKENIZER_FILES)
            if (snapshot / name).is_file()
        }
    )
    weights = files.get("model.safetensors")
    if weights is None or not weights.is_file():
        raise LocalSearchModelUnavailable("the pinned model snapshot has no model.safetensors weights")
    tokenizer_hashes = {
        name: _sha256(path)
        for name in _TOKENIZER_FILES
        if (path := files.get(name)) is not None and path.is_file()
    }
    if not tokenizer_hashes:
        raise LocalSearchModelUnavailable("the pinned model snapshot has no tokenizer files")
    return _sha256(weights), tokenizer_hashes


def build_local_search_manifest(
    embedding_profile: str = DEFAULT_EMBEDDING_PROFILE,
    *,
    snapshot_paths: Mapping[str, Path] | None = None,
    python_version: str | None = None,
) -> dict[str, object]:
    """Build a hash-bearing record for cached pinned model files only."""

    try:
        embedding_spec = _EMBEDDING_PROFILES[embedding_profile]
    except (KeyError, TypeError) as error:
        raise ValueError("embedding_profile must be small or base") from error
    model_specs = (
        (embedding_spec, "embedding"),
        ({
            "model_id": RERANKER_MODEL_ID,
            "revision": RERANKER_MODEL_REVISION,
            "license": RERANKER_LICENSE,
        }, "reranker"),
    )
    resolved_paths = dict(snapshot_paths or {})
    resolved_files: dict[str, dict[str, Path]] = {}
    if snapshot_paths is None:
        try:
            from huggingface_hub import try_to_load_from_cache

            for spec, _role in model_specs:
                model_id = str(spec["model_id"])
                revision = str(spec["revision"])
                files = {}
                for name in ("model.safetensors", *_TOKENIZER_FILES):
                    cached_path = try_to_load_from_cache(model_id, name, revision=revision)
                    if isinstance(cached_path, str):
                        files[name] = Path(cached_path)
                resolved_files[model_id] = files
        except Exception as error:
            raise LocalSearchModelUnavailable(
                "pinned local model files are missing; model manifest generation does not download files"
            ) from error

    models: dict[str, dict[str, object]] = {}
    for spec, role in model_specs:
        model_id = str(spec["model_id"])
        snapshot = resolved_paths.get(model_id)
        files = resolved_files.get(model_id)
        if snapshot is None and files is None:
            raise LocalSearchModelUnavailable(f"the pinned local snapshot for {model_id} is missing")
        try:
            weights_hash, tokenizer_hashes = _model_file_hashes(
                Path(snapshot) if snapshot is not None else files or {}
            )
        except OSError as error:
            raise LocalSearchModelUnavailable(f"the pinned local snapshot for {model_id} is incomplete") from error
        model_record: dict[str, object] = {
            "model_id": model_id,
            "revision": spec["revision"],
            "license": spec["license"],
            "weights_sha256": weights_hash,
            "tokenizer_sha256": tokenizer_hashes,
        }
        if role == "embedding":
            model_record["dimensions"] = spec["dimensions"]
        else:
            model_record["max_length"] = RERANKER_MAX_LENGTH
        models[role] = model_record

    try:
        runtime = {
            "python": python_version or platform.python_version(),
            "sentence_transformers": package_version("sentence-transformers"),
            "torch": package_version("torch"),
            "huggingface_hub": package_version("huggingface-hub"),
        }
    except PackageNotFoundError as error:
        raise LocalSearchModelUnavailable("local search runtime versions are unavailable") from error
    embedding_record = models["embedding"]
    reranker_record = models["reranker"]
    return {
        "manifest_version": 1,
        "embedding_profile": embedding_profile,
        "embedding": embedding_record,
        "reranker": reranker_record,
        # Retain the prior benchmark manifest keys for existing report readers.
        "embedding_model_id": embedding_record["model_id"],
        "embedding_model_revision": embedding_record["revision"],
        "embedding_dimensions": embedding_record["dimensions"],
        "reranker_model_id": reranker_record["model_id"],
        "reranker_model_revision": reranker_record["revision"],
        "runtime": runtime,
        "local_files_only": True,
        "trust_remote_code": False,
    }


class LocalSearchModels:
    """Lazily load the pinned models from cache, never contacting a provider."""

    def __init__(self, *, embedding_profile: str = DEFAULT_EMBEDDING_PROFILE) -> None:
        try:
            self._embedding_spec = _EMBEDDING_PROFILES[embedding_profile]
        except (KeyError, TypeError) as error:
            raise ValueError("embedding_profile must be small or base") from error
        self.embedding_profile = embedding_profile
        self.embedding_model_id = str(self._embedding_spec["model_id"])
        self.embedding_model_revision = str(self._embedding_spec["revision"])
        self._embedding: Any | None = None
        self._reranker: Any | None = None
        self._lock = RLock()

    def embed_query(self, text: str) -> list[float]:
        values = self._encode([f"query: {text}"])[0]
        if len(values) != self.embedding_dimensions:
            raise LocalSearchModelUnavailable("multilingual embedding returned an unexpected vector size")
        return values

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._encode([f"passage: {text}" for text in texts])
        if any(len(vector) != self.embedding_dimensions for vector in vectors):
            raise LocalSearchModelUnavailable("multilingual embedding returned an unexpected vector size")
        return vectors

    def rerank(self, query: str, candidates: Sequence[str]) -> list[float]:
        if not candidates:
            return []
        model = self._get_reranker()
        try:
            scores = model.predict(
                [(query, candidate) for candidate in candidates],
                batch_size=16,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return [float(score) for score in scores]
        except Exception as error:
            raise LocalSearchModelUnavailable("the local multilingual reranker could not score candidates") from error

    @property
    def embedding_dimensions(self) -> int:
        return int(self._embedding_spec["dimensions"])

    @staticmethod
    def manifest(embedding_profile: str = DEFAULT_EMBEDDING_PROFILE) -> dict[str, object]:
        return build_local_search_manifest(embedding_profile)

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._get_embedding()
        try:
            vectors = model.encode(
                list(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=32,
            )
            return [[float(value) for value in vector] for vector in vectors]
        except Exception as error:
            raise LocalSearchModelUnavailable("the local multilingual embedding model could not encode text") from error

    def _get_embedding(self) -> Any:
        with self._lock:
            if self._embedding is not None:
                return self._embedding
            try:
                from sentence_transformers import SentenceTransformer

                self._embedding = SentenceTransformer(
                    str(self._embedding_spec["model_id"]),
                    revision=str(self._embedding_spec["revision"]),
                    device="cpu",
                    local_files_only=True,
                    trust_remote_code=False,
                )
            except Exception as error:
                raise LocalSearchModelUnavailable(
                    "the pinned multilingual embedding model is not installed; run the local model download command"
                ) from error
            return self._embedding

    def _get_reranker(self) -> Any:
        with self._lock:
            if self._reranker is not None:
                return self._reranker
            try:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(
                    RERANKER_MODEL_ID,
                    revision=RERANKER_MODEL_REVISION,
                    device="cpu",
                    max_length=RERANKER_MAX_LENGTH,
                    local_files_only=True,
                    trust_remote_code=False,
                )
            except Exception as error:
                raise LocalSearchModelUnavailable(
                    "the pinned multilingual reranker is not installed; run the local model download command"
                ) from error
            return self._reranker


__all__ = [
    "E5_BASE_DIMENSIONS",
    "E5_BASE_LICENSE",
    "E5_BASE_MODEL_ID",
    "E5_BASE_MODEL_REVISION",
    "EMBEDDING_LICENSE",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_REVISION",
    "LocalSearchModelUnavailable",
    "LocalSearchModels",
    "RERANKER_LICENSE",
    "RERANKER_MAX_LENGTH",
    "RERANKER_MODEL_ID",
    "RERANKER_MODEL_REVISION",
    "build_local_search_manifest",
]
