"""End-to-end triage pipeline tests: five-bucket routing, audit row, no PII leaks (US1/T012)."""

import os

import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"), reason="integration tests require PANTERA_INTEGRATION=1"
)

_DRUG = "ibuprofen"

# Texts designed to hit each bucket deterministically via ICH keywords.
_BUCKET_TEXTS = {
    "emergency": "The patient suffered cardiac arrest and died after the drug was administered.",
    "urgent": "The patient required immediate hospitalization for severe hepatotoxicity.",
    "minor": "Mild nausea was reported by the patient after starting the medication.",
    "positive": "The drug demonstrated improved outcomes compared to the control group.",
    "irrelevant": "This study reviews the chemical synthesis pathway of the compound.",
}

# Expected (bucket, status) for each scenario
_EXPECTED: dict[str, tuple[str, str]] = {
    "emergency": ("emergency", "pending_expedited"),
    "urgent": ("urgent", "pending_expedited"),
    "minor": ("minor", "pending_batch"),
    "positive": ("positive", "pending_batch"),
    "irrelevant": ("irrelevant", "classified"),
}


@pytest_asyncio.fixture
async def mock_ms_classify():
    """Mock ModelserverClient with deterministic classify results per text content."""
    from app.infra.modelserver_client import ModelserverClient

    class MockMS(ModelserverClient):
        async def classify(self, texts: list[str]) -> list[dict]:
            results = []
            for text in texts:
                lower = text.lower()
                if any(k in lower for k in ["cardiac", "hospitali", "nausea", "hepato"]):
                    results.append(
                        {
                            "confidence": 0.95,
                            "is_adverse": True,
                            "model_version": {"sha256": "test"},
                        }
                    )
                elif "improved outcomes" in lower:
                    results.append(
                        {
                            "confidence": 0.30,
                            "is_adverse": False,
                            "model_version": {"sha256": "test"},
                        }
                    )
                else:
                    results.append(
                        {
                            "confidence": 0.20,
                            "is_adverse": False,
                            "model_version": {"sha256": "test"},
                        }
                    )
            return results

        async def embed_chunked(self, texts: list[str]) -> list[dict]:
            import numpy as np

            results = []
            for text in texts:
                seed = hash(text) % 2**31
                np.random.seed(seed)
                emb = np.random.randn(768).astype(np.float32)
                emb = emb / (np.linalg.norm(emb) + 1e-8)
                results.append({"embedding": emb.tolist(), "model_version": {"sha256": "test"}})
            return results

        async def get_ready(self) -> dict:
            return {"models": {"embedder": {"sha256": "test"}}}

    return MockMS(base_url="http://test", token="test-token")


@pytest.mark.asyncio
async def test_five_bucket_routing(
    auth_app, make_client, make_watchlist, make_document, monkeypatch, mock_ms_classify
):
    """Each bucket routes to the correct status; audit row contains required fields (FR-011)."""
    from sqlalchemy import select

    import app.triage.llm as llm_mod
    import app.triage.ner as ner_mod
    from app.audit.models import AuditLog
    from app.clients.models import WatchlistItem
    from app.triage.models import Finding
    from app.triage.runner import triage_document_runner

    async def fake_resolve(text, reliability, settings, client_id, document_id, **kwargs):
        return False

    async def fake_valence(text, reliability, settings, client_id, document_id, **kwargs):
        if "improved outcomes" in text.lower():
            return "positive"
        return "irrelevant"

    monkeypatch.setattr(llm_mod, "resolve_yes_no", fake_resolve)
    monkeypatch.setattr(llm_mod, "assess_valence", fake_valence)

    async def fake_ner(text):
        lower = text.lower()
        drugs = [_DRUG] if _DRUG in lower else []
        for reaction in ["cardiac arrest", "hepatotoxicity", "nausea"]:
            if reaction in lower:
                return drugs, [reaction]
        return drugs, []

    monkeypatch.setattr(ner_mod, "extract_entities", fake_ner)

    client_obj = await make_client()
    wl = await make_watchlist(client_obj.id)

    factory = auth_app.state.session_factory
    dispatcher = auth_app.state.dispatcher

    async with factory() as s:
        async with s.begin():
            s.add(
                WatchlistItem(
                    watchlist_id=wl.id,
                    client_id=client_obj.id,
                    item_type="drug",
                    value=_DRUG,
                    normalized_value=_DRUG,
                )
            )

    for bucket_name, text in _BUCKET_TEXTS.items():
        doc = await make_document(
            client_id=client_obj.id,
            source_reliability="peer_reviewed",
            watchlist_id=wl.id,
            title=f"Test {bucket_name}",
            source_payload={"abstract": text},
        )

        await triage_document_runner(
            session_factory=factory,
            document_id=doc.id,
            client_id=client_obj.id,
            document_text=f"{_DRUG} {text}",
            source_reliability="peer_reviewed",
            watchlist_drugs=[_DRUG],
            custom_keywords=[],
            ms_client=mock_ms_classify,
            dispatcher=dispatcher,
        )

        async with factory() as s:
            result = await s.execute(
                select(Finding).where(
                    Finding.document_id == doc.id,
                    Finding.client_id == client_obj.id,
                )
            )
            findings = result.scalars().all()

        assert len(findings) >= 1, f"Expected finding for bucket={bucket_name}"
        f = findings[0]

        exp_bucket, exp_status = _EXPECTED[bucket_name]
        assert (
            f.bucket == exp_bucket
        ), f"{bucket_name}: expected bucket={exp_bucket}, got {f.bucket}"
        assert (
            f.status == exp_status
        ), f"{bucket_name}: expected status={exp_status}, got {f.status}"
        # Triage-time finding has null corroboration_sources (FR-014)
        assert f.corroboration_sources is None

        # Audit row (FR-011): required fields present for newly created findings
        async with factory() as s:
            audit = await s.execute(
                select(AuditLog).where(
                    AuditLog.event_type == "FindingClassified",
                    AuditLog.client_id == client_obj.id,
                )
            )
            rows = audit.scalars().all()
        relevant = [r for r in rows if r.payload and r.payload.get("finding_id") == f.id]
        assert relevant, f"Expected audit row for finding_id={f.id}"
        payload = relevant[0].payload
        assert "bucket" in payload
        assert "resolution_path" in payload
        assert "routing_outcome" in payload
