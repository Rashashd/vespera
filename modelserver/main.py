"""FastAPI app factory and lifespan for the modelserver.

Lifespan: load secret → validate artifacts → load inference sessions → set ready.
The lifespan call site for validate_artifacts is intentionally kept here so US4's
startup.py refinements fill in enforcement without missing wiring (T013 note).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response

if TYPE_CHECKING:
    pass

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",
}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot: load token + validate artifacts + load sessions; sets app.state.ready."""
    from modelserver.core.config import ModelserverConfig
    from modelserver.core.logging import configure_logging, get_logger
    from modelserver.core.manifest import Manifest
    from modelserver.core.startup import load_modelserver_token, validate_artifacts
    from modelserver.inference.classifier import ClassifierSession
    from modelserver.inference.embedder import EmbedderSession
    from modelserver.inference.tokenize import load_tokenizer

    config: ModelserverConfig = app.state.config
    configure_logging(config.log_level)
    log = get_logger(__name__)

    # 1. Service credential (refuse boot if empty — D5/FR-016)
    app.state.service_token = load_modelserver_token(config)

    # 2. Artifact integrity validation (refuse boot on mismatch/absence — FR-010/US4)
    model_dir = Path(config.model_dir)
    manifest = Manifest(model_dir)
    validate_artifacts(model_dir, manifest.raw)

    # 3. Load tokenizer (shared by classifier if ONNX, and by embedder)
    tok_entry = manifest.artifact("tokenizer")
    tokenizer = load_tokenizer(str(model_dir / tok_entry["file"]))

    # 4. Load classifier session
    clf_entry = manifest.artifact("classifier")
    classifier = ClassifierSession(
        model_dir / clf_entry["file"],
        tokenizer=tokenizer if clf_entry["format"] == "onnx" else None,
        max_tokens=config.max_tokens,
    )

    # 5. Load embedder session
    emb_entry = manifest.artifact("embedder")
    embedder = EmbedderSession(
        model_dir / emb_entry["file"],
        tokenizer=tokenizer,
        max_tokens=config.max_tokens,
    )

    # 6. Publish on app.state
    app.state.manifest = manifest
    app.state.classifier = classifier
    app.state.embedder = embedder
    app.state.model_versions = {
        "classifier": {
            "version": clf_entry["version"],
            "sha256": clf_entry["sha256"],
            "format": clf_entry["format"],
        },
        "embedder": {
            "version": emb_entry["version"],
            "sha256": emb_entry["sha256"],
            "format": emb_entry["format"],
            "dim": emb_entry.get("dim", 768),
            "max_tokens": emb_entry.get("max_tokens", 512),
        },
    }
    app.state.ready = True
    log.info("modelserver.ready")

    yield

    app.state.ready = False


def create_app() -> FastAPI:
    """Create and configure the modelserver FastAPI application."""
    from modelserver.core.config import get_config
    from modelserver.routes import router

    config = get_config()
    app = FastAPI(
        title="Pantera Modelserver",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.config = config
    app.state.ready = False
    app.include_router(router)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    return app


app = create_app()
