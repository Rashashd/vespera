"""RAG eval gate: hit@5, MRR, corroboration_accuracy vs thresholds (T046 / FR-024–026).

Boots the modelserver ASGI app in-process against the committed model artifacts so no
separate modelserver container is needed. Skipped when onnxruntime is absent.

FR-026 improvement proof: asserts hybrid+rerank ≥ dense-only on hit@5 and MRR.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("PANTERA_INTEGRATION"),
        reason="requires PANTERA_INTEGRATION=1 and docker compose up",
    ),
    pytest.mark.skipif(
        find_spec("onnxruntime") is None,
        reason="onnxruntime not installed",
    ),
]

# ---------------------------------------------------------------------------
# Golden corpus — each entry becomes a Document with explicit normalized_external_id
# ---------------------------------------------------------------------------

_PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>{title}</ArticleTitle>
    <Abstract><AbstractText>{content}</AbstractText></Abstract>
  </Article>
</PubmedArticle>"""

_EVAL_CORPUS = [
    {
        "ext_id": "eval:hepato-1",
        "title": "Drug induced hepatotoxicity liver damage ALT elevation",
        "content": (
            "Drug induced hepatotoxicity causes liver damage with elevated ALT AST enzymes. "
            "Patients developed hepatotoxicity after drug administration with liver failure."
        ),
    },
    {
        "ext_id": "eval:hepato-2",
        "title": "Hepatotoxicity liver injury drug adverse event",
        "content": (
            "Hepatotoxicity liver injury drug induced adverse event reported in clinical study. "
            "Patients showed liver damage elevated transaminases drug hepatotoxicity confirmed."
        ),
    },
    {
        "ext_id": "eval:qt-1",
        "title": "QT prolongation cardiac arrhythmia azithromycin",
        "content": (
            "QT prolongation cardiac arrhythmia associated with azithromycin antibiotic. "
            "Patients developed QT interval prolongation cardiac events after azithromycin."
        ),
    },
    {
        "ext_id": "eval:renal-1",
        "title": "Renal failure nephrotoxicity contrast agent kidney",
        "content": (
            "Renal failure nephrotoxicity induced by iodinated contrast agent in patients. "
            "Contrast nephropathy renal failure creatinine elevation kidney damage observed."
        ),
    },
    {
        "ext_id": "eval:sjs-1",
        "title": "Stevens Johnson syndrome toxic epidermal necrolysis drug",
        "content": (
            "Stevens Johnson syndrome toxic epidermal necrolysis severe cutaneous drug reaction. "
            "Patients developed Stevens Johnson syndrome after drug exposure skin blistering."
        ),
    },
    {
        "ext_id": "eval:sjs-2",
        "title": "Toxic epidermal necrolysis Stevens Johnson drug adverse",
        "content": (
            "Toxic epidermal necrolysis Stevens Johnson syndrome severe drug adverse reaction. "
            "Severe cutaneous reactions Stevens Johnson toxic epidermal drug induced reactions."
        ),
    },
    {
        "ext_id": "eval:allergy-1",
        "title": "Anaphylaxis allergic reaction penicillin beta-lactam",
        "content": (
            "Anaphylaxis severe allergic reaction following penicillin beta-lactam antibiotic. "
            "Patients experienced anaphylaxis anaphylactic shock penicillin allergic reaction."
        ),
    },
    {
        "ext_id": "eval:bleed-1",
        "title": "Bleeding hemorrhage anticoagulant warfarin adverse",
        "content": (
            "Bleeding hemorrhage risk with anticoagulant warfarin therapy adverse events. "
            "Major bleeding hemorrhage warfarin anticoagulation gastrointestinal adverse event."
        ),
    },
    {
        "ext_id": "eval:bleed-2",
        "title": "Hemorrhage warfarin anticoagulant NSAID bleeding risk",
        "content": (
            "Hemorrhage warfarin anticoagulant interaction with NSAID increases bleeding risk. "
            "Patients on warfarin NSAID concomitant use showed bleeding hemorrhage adverse events."
        ),
    },
    {
        "ext_id": "eval:bleed-3",
        "title": "Anticoagulant warfarin bleeding complication adverse event",
        "content": (
            "Anticoagulant warfarin therapy bleeding hemorrhage complications adverse events. "
            "Spontaneous bleeding intracranial hemorrhage warfarin anticoagulant dose related."
        ),
    },
    {
        "ext_id": "eval:neutro-1",
        "title": "Neutropenia agranulocytosis bone marrow suppression drug",
        "content": (
            "Neutropenia agranulocytosis severe bone marrow suppression drug adverse event. "
            "Drug induced neutropenia agranulocytosis white cell bone marrow suppression."
        ),
    },
    {
        "ext_id": "eval:myop-1",
        "title": "Myopathy rhabdomyolysis statin myalgia creatine kinase",
        "content": (
            "Statin induced myopathy rhabdomyolysis elevated creatine kinase myalgia adverse. "
            "Patients on statin therapy developed myopathy rhabdomyolysis muscle pain myalgia."
        ),
    },
    {
        "ext_id": "eval:pulm-1",
        "title": "Pulmonary fibrosis interstitial lung disease amiodarone",
        "content": (
            "Amiodarone induced pulmonary fibrosis interstitial lung disease adverse event. "
            "Pulmonary toxicity amiodarone interstitial lung fibrosis pneumonitis adverse."
        ),
    },
    {
        "ext_id": "eval:hypo-1",
        "title": "Hypoglycemia severe insulin glucose adverse event",
        "content": (
            "Severe hypoglycemia insulin overdose low blood glucose adverse event patients. "
            "Insulin induced hypoglycemia glucose depression adverse event hospitalisation."
        ),
    },
    {
        "ext_id": "eval:tardive-1",
        "title": "Tardive dyskinesia antipsychotic haloperidol movement",
        "content": (
            "Tardive dyskinesia involuntary movement disorder antipsychotic haloperidol long term. "
            "Antipsychotic induced tardive dyskinesia haloperidol prolonged exposure adverse."
        ),
    },
    {
        "ext_id": "eval:panc-1",
        "title": "Pancreatitis acute abdominal enzyme elevation drug",
        "content": (
            "Acute pancreatitis drug induced abdominal pain enzyme elevation lipase amylase. "
            "Drug induced acute pancreatitis abdominal pain elevated pancreatic enzymes adverse."
        ),
    },
    {
        "ext_id": "eval:neuro-1",
        "title": "Peripheral neuropathy neurotoxicity chemotherapy induced",
        "content": (
            "Peripheral neuropathy neurotoxicity induced by chemotherapy agents adverse event. "
            "Chemotherapy induced peripheral neuropathy sensory motor neurotoxicity adverse."
        ),
    },
    {
        "ext_id": "eval:htn-1",
        "title": "Hypertension blood pressure elevation bevacizumab VEGF",
        "content": (
            "Bevacizumab VEGF inhibitor induced hypertension elevated blood pressure adverse. "
            "Anti-VEGF bevacizumab therapy blood pressure elevation hypertension adverse events."
        ),
    },
    {
        "ext_id": "eval:htn-2",
        "title": "Blood pressure hypertension bevacizumab angiogenesis drug",
        "content": (
            "Hypertension blood pressure elevation bevacizumab angiogenesis inhibitor adverse. "
            "Bevacizumab bevacizumab hypertension systolic blood pressure elevation drug."
        ),
    },
    {
        "ext_id": "eval:angio-1",
        "title": "Angioedema bradykinin ACE inhibitor swelling adverse",
        "content": (
            "Angioedema bradykinin mediated swelling ACE inhibitor adverse event patients. "
            "ACE inhibitor bradykinin angioedema facial swelling adverse drug reaction reported."
        ),
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_REAL_MODELS_DIR = Path(__file__).parent.parent.parent / "modelserver" / "models"


@pytest_asyncio.fixture(scope="module")
async def eval_ms_app():
    """Boot modelserver with the committed real model artifacts (no reranker yet)."""
    # Skip when LFS hasn't been downloaded — pointer file is ~133 bytes.
    onnx_path = _REAL_MODELS_DIR / "classifier.onnx"
    try:
        real_onnx = onnx_path.stat().st_size > 1_000_000
    except OSError:
        real_onnx = False
    if not real_onnx:
        pytest.skip("Real ONNX artifacts not present (lfs not downloaded)")

    _prev_model_dir = os.environ.get("MODEL_DIR")
    _prev_token = os.environ.get("MODELSERVER_TOKEN")
    try:
        os.environ["MODEL_DIR"] = str(_REAL_MODELS_DIR)
        os.environ["MODELSERVER_TOKEN"] = "eval-test-token"  # gitleaks:allow
        from modelserver.main import create_app

        app = create_app()
        async with app.router.lifespan_context(app):
            yield app
    finally:
        # Restore (not pop) so session-scoped fixtures that set these vars still work.
        # try/finally ensures cleanup runs even when lifespan setup raises (e.g. SHA mismatch).
        if _prev_model_dir is not None:
            os.environ["MODEL_DIR"] = _prev_model_dir
        else:
            os.environ.pop("MODEL_DIR", None)
        if _prev_token is not None:
            os.environ["MODELSERVER_TOKEN"] = _prev_token
        else:
            os.environ.pop("MODELSERVER_TOKEN", None)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_eval_gate(
    eval_ms_app,
    auth_app,
    make_client,
    make_watchlist,
) -> None:
    """Seed golden corpus, run retrieval, assert metrics ≥ thresholds (FR-024–026)."""
    import httpx
    import yaml

    from app.embedding.runner import index_build_runner
    from app.infra.modelserver_client import ModelserverClient
    from app.ingestion.models import Document, DocumentSource, DocumentWatchlist
    from app.rag import service as rag_service
    from app.rag.schemas import RetrieveRequest
    from eval.rag.run_rag_eval import check_thresholds, compute_metrics, load_golden_set

    session_factory = auth_app.state.session_factory
    redis = getattr(auth_app.state, "redis", None)
    app_state = auth_app.state

    # Load golden set and thresholds
    golden_path = Path(__file__).parent.parent.parent / "eval" / "rag" / "golden_set.jsonl"
    thresholds_path = Path(__file__).parent.parent.parent / "eval_thresholds.yaml"
    golden = load_golden_set(golden_path)
    thresholds = yaml.safe_load(thresholds_path.read_text())

    # Set up the in-process ModelserverClient pointing at the real models
    transport = httpx.ASGITransport(app=eval_ms_app)
    ms_client = ModelserverClient(
        base_url="http://modelserver",
        token="eval-test-token",  # gitleaks:allow
        transport=transport,
    )

    # Create a fresh client + watchlist for this eval run
    eval_client = await make_client(name="eval-gate-client")
    eval_wl = await make_watchlist(client_id=eval_client.id)

    # Seed the golden corpus
    async with ms_client:
        async with session_factory() as s:
            async with s.begin():
                for entry in _EVAL_CORPUS:
                    doc = Document(
                        client_id=eval_client.id,
                        normalized_external_id=entry["ext_id"],
                        title=entry["title"],
                        summary=entry["content"][:200],
                        source_reliability="peer_reviewed",
                        published_at=datetime.now(UTC),
                    )
                    s.add(doc)
                    await s.flush()
                    ds = DocumentSource(
                        document_id=doc.id,
                        client_id=eval_client.id,
                        source="pubmed",
                        source_external_id=entry["ext_id"],
                        source_reliability="peer_reviewed",
                        raw_payload=_PUBMED_XML.format(
                            title=entry["title"],
                            content=entry["content"],
                        ),
                    )
                    s.add(ds)
                    await s.flush()
                    s.add(
                        DocumentWatchlist(
                            document_id=doc.id,
                            watchlist_id=eval_wl.id,
                            client_id=eval_client.id,
                        )
                    )

        # Build chunk index via in-process modelserver
        await index_build_runner(
            session_factory=session_factory,
            client_id=eval_client.id,
            modelserver_client=ms_client,
        )

        # ---------------------------------------------------------------------------
        # Run retrieval for each golden query and collect results
        # ---------------------------------------------------------------------------

        full_results = []
        dense_only_results = []

        for case in golden:
            req = RetrieveRequest(query=case["query"], top_k=10)

            async with session_factory() as s:
                # Full pipeline (hybrid + rerank)
                resp = await rag_service.retrieve(
                    session=s,
                    redis=redis,
                    ms_client=ms_client,
                    client=eval_client,
                    req=req,
                    app_state=app_state,
                )
                full_results.append(resp.model_dump())

            # Dense-only (for improvement proof FR-026)
            from app.rag.query_embed import get_query_embedding
            from app.rag.retrieval import dense_candidates, project_passages

            async with session_factory() as s:
                qvec, _ = await get_query_embedding(
                    redis=None,  # no cache for dense-only path
                    ms_client=ms_client,
                    settings=app_state.settings,
                    app_state=app_state,
                    query=case["query"],
                )
                dense = await dense_candidates(
                    session=s,
                    client_id=eval_client.id,
                    qvec=qvec,
                    n=10,
                )
                dense_passages = await project_passages(session=s, candidates=dense[:10])
                for i, p in enumerate(dense_passages):
                    p.rank = i + 1
                    p.score = float(len(dense_passages) - i)
                dense_only_results.append(
                    {
                        "results": [json.loads(p.model_dump_json()) for p in dense_passages],
                        "corroboration_count": 0,
                    }
                )

    # ---------------------------------------------------------------------------
    # Compute and assert metrics
    # ---------------------------------------------------------------------------

    full_metrics = compute_metrics(golden, full_results)
    dense_metrics = compute_metrics(golden, dense_only_results)

    print(f"\nFull pipeline metrics: {full_metrics}")
    print(f"Dense-only metrics:    {dense_metrics}")

    failures = check_thresholds(full_metrics, thresholds)
    assert not failures, "RAG eval gate FAILED:\n" + "\n".join(failures)

    # FR-026: hybrid+rerank must be at least as good as dense-only
    assert (
        full_metrics["hit_at_5"] >= dense_metrics["hit_at_5"]
    ), f"Hybrid hit@5 {full_metrics['hit_at_5']:.3f} < dense-only {dense_metrics['hit_at_5']:.3f}"
    assert (
        full_metrics["mrr"] >= dense_metrics["mrr"]
    ), f"Hybrid MRR {full_metrics['mrr']:.3f} < dense-only {dense_metrics['mrr']:.3f}"
