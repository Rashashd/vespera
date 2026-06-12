"""Versioned ICH E2E seriousness keyword→tier artifact (six criteria, v1.0).

Maps finding/reaction text keywords to severity tiers per ICH E2E guideline.
EMERGENCY tier = life-threatening criteria; URGENT = serious (hospitalization etc).
"""

from __future__ import annotations

# ICH_KEYWORDS: mapping of lowercase substring → Bucket tier string.
# Six ICH E2E seriousness criteria enumerated; order does not affect outcome
# (severity.py picks the maximum rank across all matches).
ICH_KEYWORDS: dict[str, str] = {
    # Criterion 1: life-threatening
    "life-threatening": "emergency",
    "life threatening": "emergency",
    "cardiac arrest": "emergency",
    "respiratory arrest": "emergency",
    "anaphylactic shock": "emergency",
    "anaphylaxis": "emergency",
    "coma": "emergency",
    "status epilepticus": "emergency",
    "acute liver failure": "emergency",
    "acute renal failure": "emergency",
    "acute kidney failure": "emergency",
    "multi-organ failure": "emergency",
    "multiorgan failure": "emergency",
    # Criterion 2: death
    "death": "emergency",
    "fatal": "emergency",
    "lethal": "emergency",
    # Criterion 3: hospitalization / prolonged
    "hospitali": "urgent",  # hospitaliz(ation/ed) + hospitalIS(ation/ed)
    "inpatient": "urgent",
    "icu admission": "urgent",
    "intensive care": "urgent",
    "emergency department": "urgent",
    "emergency room": "urgent",
    "surgical intervention": "urgent",
    # Criterion 4: persistent or significant disability/incapacity
    "disability": "urgent",
    "incapacity": "urgent",
    "permanent damage": "urgent",
    "irreversible": "urgent",
    # Criterion 5: congenital anomaly / birth defect
    "congenital": "urgent",
    "birth defect": "urgent",
    "teratogen": "urgent",
    "fetal": "urgent",
    "foetal": "urgent",
    # Criterion 6: medically important — serious reactions common in pharmacovigilance
    "serious adverse": "urgent",
    "severe": "urgent",
    "toxic": "urgent",
    "toxicity": "urgent",
    "overdose": "urgent",
    "thrombosis": "urgent",
    "stroke": "urgent",
    "myocardial infarction": "urgent",
    "heart attack": "urgent",
    "pulmonary embolism": "urgent",
    "agranulocytosis": "urgent",
    "stevens-johnson": "urgent",
    "toxic epidermal necrolysis": "urgent",
    "rhabdomyolysis": "urgent",
    "pancreatitis": "urgent",
    "seizure": "urgent",
    "convulsion": "urgent",
}

VERSION = "1.0"
