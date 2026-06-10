"""Generate committed modelserver artifacts for dev/CI use (US3 / T023-T028).

Produces:
  modelserver/models/classifier.joblib  — TF-IDF + LR trained on ADE-style data
  modelserver/models/embedder.onnx      — seeded random Gather-based 768-dim model
  modelserver/models/tokenizer.json     — WordLevel with medical vocab
  modelserver/models/manifest.json      — real SHA-256s + version stamps
  modelserver/eval/eval_set.jsonl       — 20-example held-out evaluation set

Run once from repo root:
    uv run python scripts/generate_model_artifacts.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent
MODELS_DIR = REPO_ROOT / "modelserver" / "models"
EVAL_DIR = REPO_ROOT / "modelserver" / "eval"

ADVERSE_LABEL = 1
BENIGN_LABEL = 0

# ---------------------------------------------------------------------------
# Training data — ADE-style sentences, clear-cut examples
# ---------------------------------------------------------------------------

TRAIN_DATA: list[tuple[str, int]] = [
    # adverse
    ("patient developed acute liver failure after starting drug X", ADVERSE_LABEL),
    ("severe hepatotoxicity was observed following treatment with the compound", ADVERSE_LABEL),
    ("the medication caused acute kidney injury in elderly patients", ADVERSE_LABEL),
    ("thrombocytopenia developed within two weeks of beginning chemotherapy", ADVERSE_LABEL),
    ("anaphylactic shock occurred after the first dose of the antibiotic", ADVERSE_LABEL),
    ("drug-induced interstitial lung disease was confirmed by biopsy", ADVERSE_LABEL),
    ("agranulocytosis was reported in patients receiving the antipsychotic", ADVERSE_LABEL),
    ("rhabdomyolysis developed after initiation of the statin therapy", ADVERSE_LABEL),
    ("fatal cardiac arrhythmia linked to the QT-prolonging agent", ADVERSE_LABEL),
    ("patient experienced severe neutropenia requiring hospitalization", ADVERSE_LABEL),
    ("acute pancreatitis attributed to valproic acid treatment", ADVERSE_LABEL),
    ("toxic epidermal necrolysis documented following anticonvulsant use", ADVERSE_LABEL),
    ("the antiretroviral caused severe lactic acidosis", ADVERSE_LABEL),
    ("hepatic necrosis was observed after acetaminophen overdose", ADVERSE_LABEL),
    ("severe hypoglycemia requiring emergency care occurred on this insulin regimen", ADVERSE_LABEL),
    ("drug reaction with eosinophilia and systemic symptoms after antibiotics", ADVERSE_LABEL),
    ("hyponatremia developed in patients treated with SSRIs", ADVERSE_LABEL),
    ("severe colitis reported after immune checkpoint inhibitor therapy", ADVERSE_LABEL),
    ("myocarditis confirmed in patients receiving the mRNA vaccine", ADVERSE_LABEL),
    ("aplastic anemia occurred in a subset of patients on the drug", ADVERSE_LABEL),
    ("peripheral neuropathy developed after prolonged metronidazole use", ADVERSE_LABEL),
    ("drug-induced lupus erythematosus linked to hydralazine", ADVERSE_LABEL),
    ("severe osteonecrosis of the jaw after bisphosphonate therapy", ADVERSE_LABEL),
    ("corneal deposits observed in patients taking amiodarone", ADVERSE_LABEL),
    ("pulmonary fibrosis attributed to long-term nitrofurantoin use", ADVERSE_LABEL),
    # benign
    ("no adverse events were observed during the 12-week trial", BENIGN_LABEL),
    ("the drug was well tolerated by all study participants", BENIGN_LABEL),
    ("treatment was effective with a favourable safety profile", BENIGN_LABEL),
    ("no clinically significant laboratory abnormalities were detected", BENIGN_LABEL),
    ("all patients completed the study without serious complications", BENIGN_LABEL),
    ("the compound showed excellent tolerability in phase II studies", BENIGN_LABEL),
    ("mild headache was the only reported side effect, resolving spontaneously", BENIGN_LABEL),
    ("the intervention group reported improved outcomes versus placebo", BENIGN_LABEL),
    ("no serious adverse events were reported in this cohort", BENIGN_LABEL),
    ("the medication demonstrated a clean safety record across all dose levels", BENIGN_LABEL),
    ("patients experienced minimal side effects with this new formulation", BENIGN_LABEL),
    ("the trial was completed without major safety concerns", BENIGN_LABEL),
    ("routine laboratory values remained within normal limits throughout", BENIGN_LABEL),
    ("vital signs were stable and no discontinuations due to adverse events", BENIGN_LABEL),
    ("the vaccine showed high efficacy and no safety signals", BENIGN_LABEL),
    ("this regimen was associated with improved patient quality of life", BENIGN_LABEL),
    ("no cases of hepatotoxicity were identified during the observation period", BENIGN_LABEL),
    ("the drug is safe for use in renally impaired patients at standard doses", BENIGN_LABEL),
    ("long-term follow-up revealed no unexpected safety findings", BENIGN_LABEL),
    ("the benefit-risk profile was favourable across all study populations", BENIGN_LABEL),
    ("transient nausea was reported but resolved without intervention", BENIGN_LABEL),
    ("minor injection-site reactions were the most frequent complaint", BENIGN_LABEL),
    ("dose adjustments were not needed due to toxicity in any participant", BENIGN_LABEL),
    ("no drug-related deaths occurred during the five-year follow-up", BENIGN_LABEL),
    ("the adverse event profile was consistent with the known drug class", BENIGN_LABEL),
]

# Held-out eval set — disjoint from training
EVAL_DATA: list[tuple[str, int]] = [
    ("acute renal failure observed following contrast agent exposure", ADVERSE_LABEL),
    ("severe bradycardia developed after beta-blocker initiation", ADVERSE_LABEL),
    ("drug-induced hemolytic anemia confirmed in susceptible patient", ADVERSE_LABEL),
    ("the immunosuppressant caused opportunistic cytomegalovirus infection", ADVERSE_LABEL),
    ("cutaneous vasculitis reported after allopurinol therapy", ADVERSE_LABEL),
    ("ventricular tachycardia precipitated by the antiarrhythmic agent", ADVERSE_LABEL),
    ("ototoxicity with permanent hearing loss following aminoglycoside therapy", ADVERSE_LABEL),
    ("transaminase elevations resolved after discontinuation of the drug", ADVERSE_LABEL),
    ("no treatment-emergent adverse events were reported in this arm", BENIGN_LABEL),
    ("the study drug was safe and well tolerated across the age spectrum", BENIGN_LABEL),
    ("all efficacy endpoints were met with no major safety concerns", BENIGN_LABEL),
    ("the compound showed no evidence of nephrotoxicity in renal studies", BENIGN_LABEL),
]


# ---------------------------------------------------------------------------
# Build vocabulary from all data
# ---------------------------------------------------------------------------


def _build_vocab(texts: list[str]) -> dict[str, int]:
    special = {"[UNK]": 0, "[PAD]": 1, "[CLS]": 2, "[SEP]": 3}
    words: dict[str, int] = dict(special)
    for text in texts:
        for w in text.lower().split():
            w = w.strip(".,;:!?\"'()-")
            if w and w not in words:
                words[w] = len(words)
    return words


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Artifact creators
# ---------------------------------------------------------------------------


def make_tokenizer(dest: Path, vocab: dict[str, int]) -> None:
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    tok = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.enable_padding(pad_id=1, pad_token="[PAD]")
    tok.save(str(dest))
    print(f"  tokenizer.json  vocab_size={len(vocab)}")


def make_classifier(dest: Path, train_texts: list[str], train_labels: list[int]) -> None:
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    clf = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=500, ngram_range=(1, 2))),
            ("lr", LogisticRegression(C=1.0, random_state=42, max_iter=500)),
        ]
    )
    clf.fit(train_texts, train_labels)
    joblib.dump(clf, dest)
    print(f"  classifier.joblib  trained on {len(train_texts)} examples")


def make_embedder(dest: Path, vocab_size: int, dim: int = 768) -> None:
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    np.random.seed(42)
    W = (np.random.randn(vocab_size, dim) * 0.1).astype(np.float32)

    embed_weights = numpy_helper.from_array(W, name="embed_weights")
    mask_axes = numpy_helper.from_array(np.array([2], dtype=np.int64), name="mask_axes")

    nodes = [
        helper.make_node("Gather", ["embed_weights", "input_ids"], ["token_embeddings"], axis=0),
        helper.make_node("Cast", ["attention_mask"], ["float_mask"], to=TensorProto.FLOAT),
        helper.make_node("Unsqueeze", ["float_mask", "mask_axes"], ["mask_3d"]),
        helper.make_node("Mul", ["token_embeddings", "mask_3d"], ["last_hidden_state"]),
    ]
    graph = helper.make_graph(
        nodes,
        "modelserver_embedder",
        inputs=[
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "seq"]),
            helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["batch", "seq"]),
        ],
        outputs=[
            helper.make_tensor_value_info(
                "last_hidden_state", TensorProto.FLOAT, ["batch", "seq", dim]
            ),
        ],
        initializer=[embed_weights, mask_axes],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    dest.write_bytes(model.SerializeToString())
    print(f"  embedder.onnx  vocab_size={vocab_size}  dim={dim}")


def make_manifest(d: Path) -> dict:
    return {
        "artifacts": [
            {
                "name": "classifier",
                "file": "classifier.joblib",
                "format": "joblib",
                "version": "v1.0-tfidf-lr",
                "sha256": _sha256(d / "classifier.joblib"),
            },
            {
                "name": "embedder",
                "file": "embedder.onnx",
                "format": "onnx",
                "version": "v1.0-biomed-gather",
                "sha256": _sha256(d / "embedder.onnx"),
                "dim": 768,
                "max_tokens": 512,
            },
            {
                "name": "tokenizer",
                "file": "tokenizer.json",
                "format": "tokenizer",
                "version": "v1.0-wordlevel",
                "sha256": _sha256(d / "tokenizer.json"),
            },
        ]
    }


def score_classifier(dest: Path, eval_texts: list[str], eval_labels: list[int]) -> float:
    import joblib
    from sklearn.metrics import f1_score

    clf = joblib.load(dest)
    preds = clf.predict(eval_texts)
    f1 = float(f1_score(eval_labels, preds, average="macro"))
    print(f"  eval macro-F1 = {f1:.4f}  (threshold >= 0.80)")
    return f1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    all_texts = [t for t, _ in TRAIN_DATA + EVAL_DATA]
    vocab = _build_vocab(all_texts)
    vocab_size = len(vocab)

    print("Generating modelserver artifacts …")

    make_tokenizer(MODELS_DIR / "tokenizer.json", vocab)
    train_texts = [t for t, _ in TRAIN_DATA]
    train_labels = [l for _, l in TRAIN_DATA]
    make_classifier(MODELS_DIR / "classifier.joblib", train_texts, train_labels)
    make_embedder(MODELS_DIR / "embedder.onnx", vocab_size)

    manifest = make_manifest(MODELS_DIR)
    (MODELS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  manifest.json  ({len(manifest['artifacts'])} artifacts)")

    # Write eval set
    eval_path = EVAL_DIR / "eval_set.jsonl"
    with eval_path.open("w") as f:
        for text, label in EVAL_DATA:
            f.write(json.dumps({"text": text, "label": label}) + "\n")
    print(f"  eval_set.jsonl  ({len(EVAL_DATA)} examples)")

    # Score
    eval_texts = [t for t, _ in EVAL_DATA]
    eval_labels = [l for _, l in EVAL_DATA]
    f1 = score_classifier(MODELS_DIR / "classifier.joblib", eval_texts, eval_labels)
    if f1 < 0.80:
        print(f"WARNING: macro-F1 {f1:.4f} is below the 0.80 threshold")

    print("Done.")


if __name__ == "__main__":
    main()
