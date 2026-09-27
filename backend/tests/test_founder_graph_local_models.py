from __future__ import annotations

import sys
from types import ModuleType

from dots.founder_graph_local_models import (
    E5_BASE_DIMENSIONS,
    E5_BASE_MODEL_ID,
    E5_BASE_MODEL_REVISION,
    EMBEDDING_DIMENSIONS,
    LocalSearchModels,
    LocalSearchModelUnavailable,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    build_local_search_manifest,
)


def test_sentence_transformers_are_pinned_and_loaded_offline(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Embedding:
        def encode(self, texts, **kwargs):
            calls.append(("encode", {"texts": texts, **kwargs}))
            return [[1.0 / E5_BASE_DIMENSIONS] * E5_BASE_DIMENSIONS for _ in texts]

    class Reranker:
        def predict(self, pairs, **kwargs):
            calls.append(("predict", {"pairs": pairs, **kwargs}))
            return [0.7 for _ in pairs]

    module = ModuleType("sentence_transformers")

    def sentence_transformer(model_id, **kwargs):
        calls.append(("load_embedding", {"model_id": model_id, **kwargs}))
        return Embedding()

    def cross_encoder(model_id, **kwargs):
        calls.append(("load_reranker", {"model_id": model_id, **kwargs}))
        return Reranker()

    module.SentenceTransformer = sentence_transformer
    module.CrossEncoder = cross_encoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    models = LocalSearchModels()
    query_vector = models.embed_query("人と事業の組み合わせ")
    document_vectors = models.embed_documents(["Founder network"])
    scores = models.rerank("誰と何をするか", ["Founder network"])

    assert len(query_vector) == E5_BASE_DIMENSIONS
    assert len(document_vectors) == 1
    assert scores == [0.7]
    embedding_load = next(values for name, values in calls if name == "load_embedding")
    assert embedding_load == {
        "model_id": E5_BASE_MODEL_ID,
        "revision": E5_BASE_MODEL_REVISION,
        "device": "cpu",
        "local_files_only": True,
        "trust_remote_code": False,
    }
    reranker_load = next(values for name, values in calls if name == "load_reranker")
    assert reranker_load["model_id"] == RERANKER_MODEL_ID
    assert reranker_load["revision"] == RERANKER_MODEL_REVISION
    assert reranker_load["local_files_only"] is True
    assert reranker_load["trust_remote_code"] is False
    encoded = [values["texts"][0] for name, values in calls if name == "encode"]
    assert encoded == ["query: 人と事業の組み合わせ", "passage: Founder network"]
    pairs = next(values["pairs"] for name, values in calls if name == "predict")
    assert pairs == [("誰と何をするか", "Founder network")]


def test_e5_base_is_the_default_and_small_remains_an_explicit_evaluation_profile(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Embedding:
        def encode(self, texts, **kwargs):
            calls.append(("encode", {"texts": texts, **kwargs}))
            return [[1.0 / E5_BASE_DIMENSIONS] * E5_BASE_DIMENSIONS for _ in texts]

    module = ModuleType("sentence_transformers")

    def sentence_transformer(model_id, **kwargs):
        calls.append(("load_embedding", {"model_id": model_id, **kwargs}))
        return Embedding()

    module.SentenceTransformer = sentence_transformer
    module.CrossEncoder = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    assert LocalSearchModels().embedding_dimensions == E5_BASE_DIMENSIONS
    assert LocalSearchModels(embedding_profile="small").embedding_dimensions == EMBEDDING_DIMENSIONS
    models = LocalSearchModels(embedding_profile="base")
    assert len(models.embed_query("日英の合成検索")) == E5_BASE_DIMENSIONS
    assert models.embed_documents(["Synthetic founder idea"])[0]

    embedding_load = next(values for name, values in calls if name == "load_embedding")
    assert embedding_load == {
        "model_id": E5_BASE_MODEL_ID,
        "revision": E5_BASE_MODEL_REVISION,
        "device": "cpu",
        "local_files_only": True,
        "trust_remote_code": False,
    }
    encoded = [values["texts"][0] for name, values in calls if name == "encode"]
    assert encoded == ["query: 日英の合成検索", "passage: Synthetic founder idea"]


def test_base_missing_cache_fails_closed_without_network(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    module = ModuleType("sentence_transformers")

    def missing_cache(model_id, **kwargs):
        calls.append({"model_id": model_id, **kwargs})
        raise OSError("cached snapshot is missing")

    module.SentenceTransformer = missing_cache
    module.CrossEncoder = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    try:
        LocalSearchModels(embedding_profile="base").embed_query("synthetic query")
    except LocalSearchModelUnavailable as error:
        assert "not installed" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("missing local snapshot must stop search")

    assert calls == [{
        "model_id": E5_BASE_MODEL_ID,
        "revision": E5_BASE_MODEL_REVISION,
        "device": "cpu",
        "local_files_only": True,
        "trust_remote_code": False,
    }]


def test_model_manifest_records_pins_hashes_runtime_and_dimensions(tmp_path, monkeypatch) -> None:
    import hashlib
    import dots.founder_graph_local_models as local_models

    embedding_path = tmp_path / "e5-base"
    reranker_path = tmp_path / "mmarco"
    for path in (embedding_path, reranker_path):
        path.mkdir()
        (path / "model.safetensors").write_bytes(b"synthetic weights")
        (path / "tokenizer.json").write_bytes(b"synthetic tokenizer")

    monkeypatch.setattr(
        local_models,
        "package_version",
        lambda package: {"sentence-transformers": "5.test", "torch": "2.test", "huggingface-hub": "1.test"}[package],
    )
    manifest = build_local_search_manifest(
        "base",
        snapshot_paths={E5_BASE_MODEL_ID: embedding_path, RERANKER_MODEL_ID: reranker_path},
        python_version="3.test",
    )

    embedding = manifest["embedding"]
    reranker = manifest["reranker"]
    expected_weights = hashlib.sha256(b"synthetic weights").hexdigest()
    expected_tokenizer = hashlib.sha256(b"synthetic tokenizer").hexdigest()
    assert embedding["model_id"] == E5_BASE_MODEL_ID
    assert embedding["revision"] == E5_BASE_MODEL_REVISION
    assert embedding["license"] == "MIT"
    assert embedding["dimensions"] == E5_BASE_DIMENSIONS
    assert embedding["weights_sha256"] == expected_weights
    assert embedding["tokenizer_sha256"] == {"tokenizer.json": expected_tokenizer}
    assert reranker["model_id"] == RERANKER_MODEL_ID
    assert reranker["revision"] == RERANKER_MODEL_REVISION
    assert reranker["license"] == "Apache-2.0"
    assert reranker["weights_sha256"] == expected_weights
    assert reranker["tokenizer_sha256"] == {"tokenizer.json": expected_tokenizer}
    assert manifest["runtime"] == {
        "python": "3.test",
        "sentence_transformers": "5.test",
        "torch": "2.test",
        "huggingface_hub": "1.test",
    }
    assert manifest["embedding_model_id"] == E5_BASE_MODEL_ID
    assert manifest["embedding_model_revision"] == E5_BASE_MODEL_REVISION
    assert manifest["embedding_dimensions"] == E5_BASE_DIMENSIONS
    assert manifest["reranker_model_id"] == RERANKER_MODEL_ID
    assert manifest["reranker_model_revision"] == RERANKER_MODEL_REVISION


def test_manifest_resolves_only_cached_files_and_fails_when_missing(tmp_path, monkeypatch) -> None:
    from dots.founder_graph_local_models import LocalSearchModelUnavailable

    embedding_path = tmp_path / "e5-base"
    reranker_path = tmp_path / "mmarco"
    snapshots = {E5_BASE_MODEL_ID: embedding_path, RERANKER_MODEL_ID: reranker_path}
    for path in snapshots.values():
        path.mkdir()
        (path / "model.safetensors").write_bytes(b"weights")
        (path / "tokenizer.json").write_bytes(b"tokenizer")

    calls: list[tuple[str, str, str]] = []
    hub = ModuleType("huggingface_hub")

    def cached_file(model_id, filename, *, revision):
        calls.append((model_id, filename, revision))
        file_path = snapshots[model_id] / filename
        return str(file_path) if file_path.is_file() else None

    hub.try_to_load_from_cache = cached_file
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    import dots.founder_graph_local_models as local_models
    monkeypatch.setattr(local_models, "package_version", lambda _package: "test-version")

    manifest = build_local_search_manifest("base", python_version="3.test")
    assert manifest["embedding"]["dimensions"] == E5_BASE_DIMENSIONS
    assert {call[0] for call in calls} == {E5_BASE_MODEL_ID, RERANKER_MODEL_ID}
    assert all(call[2] in {E5_BASE_MODEL_REVISION, RERANKER_MODEL_REVISION} for call in calls)

    hub.try_to_load_from_cache = lambda *_args, **_kwargs: None
    try:
        build_local_search_manifest("base")
    except LocalSearchModelUnavailable as error:
        assert "no model.safetensors" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("missing cached files must stop manifest generation")
