"""Top-level conftest: modelserver fixture artifacts + ASGI app/client helpers.

All ML library imports (onnx, sklearn, tokenizers) are lazy so existing app tests
that skip these fixtures pay no import cost.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Generator
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

# Spec 12: the guardrails sidecar is not run in the test/CI environment (the red-team gate
# imports the rails engine directly). Disable the guardrails boundary for the suite via the
# test-only kill-switch so triage/agent/intake tests exercise their normal paths rather than the
# sidecar-unavailable fail-safe. Set BEFORE any get_settings() call. Production refuses this
# toggle (startup.check_security_boundary). Redaction stays ON (in-process; no sidecar needed).
# A dedicated test (test_guardrails_failsafe) re-enables guardrails to prove the outage fail-safe.
os.environ.setdefault("GUARDRAILS_ENABLED", "false")

# ---------------------------------------------------------------------------
# Fixture artifact helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_classifier_joblib(dest: Path) -> None:
    """Tiny TF-IDF + LogisticRegression pipeline for fixture tests."""
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    X = [
        "patient developed severe liver damage after taking drug X",
        "this medication caused acute kidney failure in elderly patients",
        "no adverse events were reported in this clinical trial",
        "the drug was well tolerated by all study participants",
    ]
    y = [1, 1, 0, 0]
    clf = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=50)),
            ("lr", LogisticRegression(random_state=42, max_iter=200)),
        ]
    )
    clf.fit(X, y)
    joblib.dump(clf, dest)


def _make_embedder_onnx(dest: Path) -> None:
    """Tiny ONNX embedder: embedding-table Gather → mask → [B, S, 768].

    Uses a seeded random embedding matrix (vocab_size=50) so different token
    sequences produce different vector directions — required for the semantic-
    sanity cosine check in test_embed_contract.
    """
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    np.random.seed(42)
    W = (np.random.randn(50, 768) * 0.1).astype(np.float32)

    embed_weights = numpy_helper.from_array(W, name="embed_weights")
    mask_axes = numpy_helper.from_array(np.array([2], dtype=np.int64), name="mask_axes")

    nodes = [
        # Gather token embeddings: input_ids [B,S] → [B, S, 768]
        helper.make_node("Gather", ["embed_weights", "input_ids"], ["token_embeddings"], axis=0),
        # Cast attention_mask int64 → float32 and unsqueeze to [B, S, 1]
        helper.make_node("Cast", ["attention_mask"], ["float_mask"], to=TensorProto.FLOAT),
        helper.make_node("Unsqueeze", ["float_mask", "mask_axes"], ["mask_3d"]),
        # Zero out pad positions
        helper.make_node("Mul", ["token_embeddings", "mask_3d"], ["last_hidden_state"]),
    ]
    graph = helper.make_graph(
        nodes,
        "fixture_embedder",
        inputs=[
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "seq"]),
            helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["batch", "seq"]),
        ],
        outputs=[
            helper.make_tensor_value_info(
                "last_hidden_state", TensorProto.FLOAT, ["batch", "seq", 768]
            ),
        ],
        initializer=[embed_weights, mask_axes],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    dest.write_bytes(model.SerializeToString())


def _make_tokenizer_json(dest: Path) -> None:
    """Minimal WordLevel tokenizer with a small medical vocabulary."""
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    vocab: dict[str, int] = {
        "[UNK]": 0,
        "[PAD]": 1,
        "[CLS]": 2,
        "[SEP]": 3,
    }
    for word in [
        "patient",
        "drug",
        "adverse",
        "event",
        "liver",
        "kidney",
        "damage",
        "treatment",
        "dose",
        "study",
        "clinical",
        "the",
        "a",
        "no",
        "was",
        "well",
        "tolerated",
        "participants",
        "developed",
        "severe",
        "acute",
        "failure",
        "elderly",
        "reported",
        "trial",
    ]:
        if word not in vocab:
            vocab[word] = len(vocab)

    tok = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.enable_padding(pad_id=1, pad_token="[PAD]")
    tok.save(str(dest))


def _make_reranker_onnx(dest: Path) -> None:
    """Tiny ONNX cross-encoder: inputs (input_ids, attention_mask, token_type_ids) → logits [B,1].

    Score = sum of attention_mask (non-pad token count), which gives different values per
    passage length — enough for ordering tests.
    """
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    reduce_axes = numpy_helper.from_array(np.array([1], dtype=np.int64), name="reduce_axes")

    nodes = [
        helper.make_node("Cast", ["attention_mask"], ["float_mask"], to=TensorProto.FLOAT),
        helper.make_node("ReduceSum", ["float_mask", "reduce_axes"], ["logits"], keepdims=1),
    ]
    graph = helper.make_graph(
        nodes,
        "fixture_reranker",
        inputs=[
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "seq"]),
            helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["batch", "seq"]),
            helper.make_tensor_value_info("token_type_ids", TensorProto.INT64, ["batch", "seq"]),
        ],
        outputs=[
            helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch", 1]),
        ],
        initializer=[reduce_axes],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    dest.write_bytes(model.SerializeToString())


def _make_reranker_tokenizer_json(dest: Path) -> None:
    """BERT-style WordLevel tokenizer with pair-encoding post-processor for reranker."""
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from tokenizers.processors import TemplateProcessing

    vocab: dict[str, int] = {"[UNK]": 0, "[PAD]": 1, "[CLS]": 2, "[SEP]": 3}
    for word in [
        "patient",
        "drug",
        "adverse",
        "event",
        "liver",
        "kidney",
        "damage",
        "treatment",
        "dose",
        "study",
        "hepatotoxicity",
        "reaction",
        "associated",
        "the",
        "a",
        "no",
        "clinical",
        "developed",
        "severe",
        "acute",
    ]:
        if word not in vocab:
            vocab[word] = len(vocab)

    tok = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.post_processor = TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", 2), ("[SEP]", 3)],
    )
    tok.enable_padding(pad_id=1, pad_token="[PAD]")
    tok.save(str(dest))


def _build_manifest(d: Path) -> dict:
    return {
        "artifacts": [
            {
                "name": "classifier",
                "file": "classifier.joblib",
                "format": "joblib",
                "version": "clf-fixture",
                "sha256": _sha256(d / "classifier.joblib"),
            },
            {
                "name": "embedder",
                "file": "embedder.onnx",
                "format": "onnx",
                "version": "emb-fixture",
                "sha256": _sha256(d / "embedder.onnx"),
                "dim": 768,
                "max_tokens": 512,
            },
            {
                "name": "tokenizer",
                "file": "tokenizer.json",
                "format": "tokenizer",
                "version": "emb-fixture",
                "sha256": _sha256(d / "tokenizer.json"),
            },
        ]
    }


# ---------------------------------------------------------------------------
# Session-scoped model directory (created once per test session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def modelserver_model_dir(tmp_path_factory) -> Generator[Path, None, None]:
    """Create tiny fixture ML artifacts and write MODEL_DIR / MODELSERVER_TOKEN env vars."""
    d = tmp_path_factory.mktemp("ms_models")

    _make_classifier_joblib(d / "classifier.joblib")
    _make_embedder_onnx(d / "embedder.onnx")
    _make_tokenizer_json(d / "tokenizer.json")
    (d / "manifest.json").write_text(json.dumps(_build_manifest(d), indent=2))

    os.environ["MODEL_DIR"] = str(d)
    os.environ["MODELSERVER_TOKEN"] = "test-service-token"  # gitleaks:allow
    yield d
    os.environ.pop("MODEL_DIR", None)
    os.environ.pop("MODELSERVER_TOKEN", None)


# ---------------------------------------------------------------------------
# Session-scoped model directory WITH reranker (for US4 tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def modelserver_model_dir_with_reranker(tmp_path_factory) -> Generator[Path, None, None]:
    """Fixture model dir with all artifacts including reranker + reranker_tokenizer."""
    d = tmp_path_factory.mktemp("ms_models_rr")

    _make_classifier_joblib(d / "classifier.joblib")
    _make_embedder_onnx(d / "embedder.onnx")
    _make_tokenizer_json(d / "tokenizer.json")
    _make_reranker_onnx(d / "reranker.onnx")
    _make_reranker_tokenizer_json(d / "reranker_tokenizer.json")

    manifest = _build_manifest(d)
    manifest["artifacts"].extend(
        [
            {
                "name": "reranker",
                "file": "reranker.onnx",
                "format": "onnx",
                "version": "rr-fixture",
                "sha256": _sha256(d / "reranker.onnx"),
                "max_tokens": 512,
            },
            {
                "name": "reranker_tokenizer",
                "file": "reranker_tokenizer.json",
                "format": "tokenizer",
                "version": "rr-fixture",
                "sha256": _sha256(d / "reranker_tokenizer.json"),
            },
        ]
    )
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))

    os.environ["MODEL_DIR"] = str(d)
    os.environ["MODELSERVER_TOKEN"] = "test-service-token"  # gitleaks:allow
    yield d
    os.environ.pop("MODEL_DIR", None)
    os.environ.pop("MODELSERVER_TOKEN", None)


# ---------------------------------------------------------------------------
# ASGI app + client (function-scoped so each test gets a fresh lifespan)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ms_app(modelserver_model_dir):
    """Boot the modelserver app against fixture artifacts via ASGI lifespan."""
    from modelserver.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def ms_client(ms_app):
    """Async ASGI client bound to the running modelserver app."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=ms_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# Convenience: pre-authed client
@pytest_asyncio.fixture
async def ms_authed(ms_client):
    """ms_client with X-Service-Token header pre-set."""
    ms_client.headers["X-Service-Token"] = "test-service-token"
    return ms_client


# ---------------------------------------------------------------------------
# Reranker-backed ASGI app + clients (function-scoped)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ms_app_with_reranker(modelserver_model_dir_with_reranker):
    """Boot modelserver with reranker artifact via ASGI lifespan."""
    from modelserver.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def ms_client_with_reranker(ms_app_with_reranker):
    """Async ASGI client bound to modelserver with reranker."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=ms_app_with_reranker)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def ms_authed_with_reranker(ms_client_with_reranker):
    """ms_client_with_reranker with X-Service-Token header pre-set."""
    ms_client_with_reranker.headers["X-Service-Token"] = "test-service-token"
    return ms_client_with_reranker
