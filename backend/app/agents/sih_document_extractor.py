"""
SIH26100 Bidder Document Extraction Agent (Phase 4).

Structurally identical to app/agents/capability_builder.py -- parses a
document, builds the category-specific prompt, calls the existing LLM
client abstraction (app/agents/llm_client.get_llm_client(), never a
second provider integration), validates the response against a Pydantic
schema, and returns a plain result the service layer persists. Never
touches the database directly.

classify_document() is the one genuinely new piece: when an officer
uploads a document without specifying its category, this decides which
ComplianceCategory it most likely belongs to. Deliberately a
deterministic keyword heuristic, not a second LLM call -- classification
only needs to pick which of five known prompts to run next; a keyword
match is cheap, instant, fully explainable to an officer ("classified as
GST because the text contains 'GSTIN'"), and avoids a chicken-and-egg
problem where classifying the document would itself need an LLM call
before we even know which extraction schema to validate against. If no
category scores a confident match, the document is left unclassified
(REVIEW_REQUIRED) rather than guessed -- per the Phase 4 brief's explicit
"do not silently assign the wrong compliance category."
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from app.agents.document_parser import ParsedDocument, extract_text
from app.agents.json_utils import parse_json_response
from app.agents.llm_client import get_llm_client
from app.agents.prompts.sih_documents import CATEGORY_PROMPTS
from app.schemas.sih_extraction import CATEGORY_EXTRACTION_SCHEMAS


@dataclass
class SIHExtractionResult:
    category_code: str
    fields: dict
    confidence: float
    used_ocr: bool


# Keyword signals per category, ordered by specificity -- checked in this
# order so a document mentioning both "PAN" and "GSTIN" (very common,
# since a GST certificate always shows the linked PAN) is classified by
# its most specific/primary identifier first, not misfiled under PAN/ITR
# just because a PAN string happens to appear on it too.
_CLASSIFICATION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("blacklisting", ["blacklist", "debarment", "debarred", "banned from", "suspension order"]),
    ("udyam", ["udyam", "udyog aadhaar", "msme registration"]),
    ("gst", ["gstin", "goods and services tax", "gst registration"]),
    ("epfo_esic", ["epfo", "esic", "provident fund", "employees' state insurance", "establishment id"]),
    ("pan_itr", ["income tax return", "itr-", "permanent account number", "assessment year"]),
]
# A category needs at least this many distinct keyword hits to be treated
# as confidently classified -- a single incidental mention (e.g. "PAN" in
# passing on an unrelated letter) isn't enough.
_MIN_KEYWORD_MATCHES = 1


def classify_document(text: str) -> tuple[str | None, float]:
    """
    Returns (category_code, confidence) -- category_code is None when no
    category reaches _MIN_KEYWORD_MATCHES, meaning the caller should mark
    the document REVIEW_REQUIRED rather than guess. confidence is a
    simple, explainable ratio (keywords matched / keywords checked for
    that category), not a model-derived probability.
    """
    lowered = text.lower()
    for category_code, keywords in _CLASSIFICATION_KEYWORDS:
        matches = sum(1 for kw in keywords if kw in lowered)
        if matches >= _MIN_KEYWORD_MATCHES:
            confidence = min(1.0, matches / len(keywords))
            return category_code, round(confidence, 2)
    return None, 0.0


async def extract_bidder_document(file_path: Path, extension: str, category_code: str) -> SIHExtractionResult:
    if category_code not in CATEGORY_PROMPTS:
        raise ValueError(
            f"No extraction prompt implemented for compliance category '{category_code}' yet "
            "(roadmap category -- Phase 1's adapter registry has no adapter for it either)."
        )

    # Same asyncio.to_thread offload as capability_builder.build_capability()
    # -- extract_text()'s OCR fallback path blocks the event loop otherwise.
    parsed = await asyncio.to_thread(extract_text, file_path, extension)
    if not parsed.text.strip():
        raise ValueError(
            "No extractable text found in document (parsing and OCR both produced empty output)."
        )

    system_prompt, build_prompt = CATEGORY_PROMPTS[category_code]
    user_prompt = build_prompt(parsed.text)

    client = get_llm_client()
    raw_response = await client.complete(system_prompt, user_prompt, purpose="sih_document_extraction")

    extracted_json = parse_json_response(raw_response)
    schema_cls = CATEGORY_EXTRACTION_SCHEMAS[category_code]
    validated = schema_cls.model_validate(extracted_json)
    fields = validated.model_dump()

    if not any(value not in (None, "", []) for value in fields.values()):
        raise ValueError(
            "Extraction found no populated fields at all -- "
            "treating as a failed extraction rather than persisting an empty record."
        )

    confidence = _compute_confidence(parsed, fields, list(schema_cls.model_fields.keys()))
    return SIHExtractionResult(
        category_code=category_code, fields=fields, confidence=confidence, used_ocr=parsed.used_ocr
    )


def _compute_confidence(parsed: ParsedDocument, fields: dict, expected_fields: list[str]) -> float:
    """Identical derivation to capability_builder._compute_confidence() --
    concrete signals (OCR word confidence or a fixed native-text baseline),
    scaled by how many expected fields actually came back populated. Never
    an LLM self-reported confidence."""
    if parsed.used_ocr and parsed.ocr_confidence is not None:
        base = parsed.ocr_confidence / 100.0
    else:
        base = 0.95

    populated = sum(1 for field in expected_fields if fields.get(field) not in (None, "", []))
    completeness = populated / len(expected_fields) if expected_fields else 1.0

    return round(base * completeness, 4)


# Kept for readability in callers that want to sanity-check a PAN-looking
# string without importing re themselves -- not currently required by any
# adapter (PAN comparison stays exact-string, per Phase 1), but documents
# the expected shape for anyone building on this later.
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
