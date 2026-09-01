"""
Tender Analysis Agent.

Pipeline: parse each attached source document into an ordered list of
"units" (a PDF page, or a spreadsheet sheet) -> chunk that combined,
cross-document list by unit count, exactly as before -> LLM extraction
per chunk (still [PAGE N]-marked, for provenance) -> deterministic
duplicate removal -> validate -> return structured requirements, now
carrying back which source document (and where in it) each requirement
came from. Persistence is tender_service.py's job, consistent with the
AI Service Layer / Business Logic Layer separation already established
(M3 follows the same split).

Multi-document support (real-CPPP-tender validation gap): a real tender
is rarely a single PDF — it commonly ships as a main PDF plus one or
more spreadsheets (technical bid detail, financial BOQ). Rather than
inventing a second, parallel extraction pipeline for spreadsheets, every
attached, non-financial-role document's content — PDF pages or
spreadsheet sheets alike — is flattened into ONE ordered sequence of
`SourceUnit`s and fed through the exact same integer-keyed chunking /
[PAGE N]-marker / LLM-prompt mechanism that already existed for
PDF-only tenders. This is deliberate: `prompts/tender_requirement.py`,
`schemas/extraction.py`, and `agents/mock_extraction.py` (which regexes
literal `[PAGE (\\d+)]` markers) all needed ZERO changes as a result —
the LLM contract's shape is identical whether "page N" happens to be a
real PDF page or a spreadsheet sheet's synthetic position in the
combined sequence. `unit_lookup` resolves the LLM's returned integer
back to the real (document, page-or-sheet) provenance after the response
comes back, which is also where the single-PDF backward-compatibility
guarantee is enforced: for a tender with exactly one PDF and no other
documents, unit numbers are assigned 1..N in PDF page order, identical
to today's behavior, so source_page on the result is byte-identical to
what this function returned before multi-document support existed.

Financial/BOQ-role documents are deliberately excluded from LLM input —
pricing line items are not tender *requirements* and sending them adds
LLM cost/noise for no extraction benefit; excluding by document_role is
a simple deterministic filter, not a second AI call.

Deliberately narrow: this module only knows how to analyze tenders. No
generic "document chunking framework" — Certifications/CVs (M3) are
short enough to never need chunking, so this logic doesn't try to serve
both use cases.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.agents.document_parser import extract_pdf_pages, extract_spreadsheet_sheets
from app.agents.json_utils import parse_json_response
from app.agents.llm_client import get_llm_client
from app.agents.prompts import tender_requirement
from app.core.config import get_settings
from app.models.enums import RequirementNature
from app.schemas.extraction import ExtractedRequirement, TenderChunkExtraction

settings = get_settings()
logger = logging.getLogger(__name__)

# Document roles excluded from LLM extraction input — see module
# docstring. Matches the lowercase role strings tender_service.py
# assigns (see its filename-based role-inference table).
_FINANCIAL_ROLES = {"financial"}

_SPREADSHEET_EXTENSIONS = {".xls", ".xlsx"}


@dataclass
class TenderSourceDocument:
    """One document attached to a Tender, as tender_service.py resolves
    it — a local filesystem path (already resolved via
    storage.local_file_for_read by the caller) plus enough identity/role
    to drive extraction and provenance."""

    document_id: uuid.UUID
    file_name: str
    document_role: str | None
    file_path: Path


@dataclass
class SourceUnit:
    """One page (PDF) or sheet (spreadsheet) after flattening every
    non-financial source document into a single ordered sequence — the
    thing that actually gets assigned a unit number and fed to the LLM
    as "[PAGE N]"."""

    document_id: uuid.UUID
    file_name: str
    label: str  # "Page 3" or "Sheet: Sheet1" — human-readable, format-agnostic
    text: str


@dataclass
class RequirementResult:
    requirement_type: str
    description: str | None
    mandatory: bool
    source_page: int | None
    source_document_id: uuid.UUID | None
    source_location: str | None
    confidence: float
    requirement_nature: str  # architecture debate Phase 1 -- see _resolve_nature()


# The three requirement_type values that are always PROCEDURAL,
# deterministically, regardless of what (if anything) the LLM returned
# for requirement_nature on that row -- see prompts/tender_requirement.py's
# NATURE_ELIGIBLE_TYPES (the complement of this set) and RequirementNature's
# docstring in app/models/enums.py.
_PROCEDURAL_TYPES = {"evaluation_criteria", "deadline", "submission"}

_VALID_ELIGIBLE_NATURES = {
    RequirementNature.CAPABILITY_CLAIM.value,
    RequirementNature.SUBMISSION_GATING.value,
    RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT.value,
}


def _resolve_nature(req: ExtractedRequirement) -> str:
    """
    Deterministic resolution of the final, persisted requirement_nature —
    the LLM's raw (and possibly absent/invalid) requirement_nature is
    never trusted as-is. Architecture debate Phase 1, see
    BidOps_Architecture_Debate.md and RequirementNature's docstring.

    1. requirement_type in _PROCEDURAL_TYPES always wins, unconditionally
       -- even if the LLM incorrectly populated requirement_nature on
       one of these rows, the deterministic override takes precedence.
    2. Otherwise, if the LLM returned one of the three valid eligible
       natures, use it as-is.
    3. Otherwise (None, empty, garbage, or "procedural" returned for an
       eligible type) fall back to CAPABILITY_CLAIM -- the fail-safe
       direction, since it is the nature with the narrowest blast
       radius downstream (routes through ordinary capability matching,
       never auto-BLOCKED the way an incorrectly-trusted
       SUBMISSION_GATING value could). This is a compatibility/fail-safe
       fallback, not a semantic claim that the requirement was proven to
       be a capability claim -- logged at WARNING so extraction-quality
       regressions are observable without a new DB column to track it.
    """
    if req.requirement_type in _PROCEDURAL_TYPES:
        return RequirementNature.PROCEDURAL.value

    if req.requirement_nature in _VALID_ELIGIBLE_NATURES:
        return req.requirement_nature

    logger.warning(
        "requirement_nature fallback to CAPABILITY_CLAIM: requirement_type=%r "
        "returned invalid/missing requirement_nature=%r",
        req.requirement_type,
        req.requirement_nature,
    )
    return RequirementNature.CAPABILITY_CLAIM.value


def _build_source_units(sources: list[TenderSourceDocument]) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    for source in sources:
        if (source.document_role or "").lower() in _FINANCIAL_ROLES:
            continue  # pricing/BOQ content — not tender requirements, see module docstring

        extension = source.file_path.suffix.lower()
        if extension in _SPREADSHEET_EXTENSIONS:
            for sheet_name, text in extract_spreadsheet_sheets(source.file_path, extension):
                units.append(
                    SourceUnit(
                        document_id=source.document_id,
                        file_name=source.file_name,
                        label=f"Sheet: {sheet_name}",
                        text=text,
                    )
                )
        else:
            pages = extract_pdf_pages(source.file_path)
            for page_num, text in enumerate(pages, start=1):
                units.append(
                    SourceUnit(
                        document_id=source.document_id,
                        file_name=source.file_name,
                        label=f"Page {page_num}",
                        text=text,
                    )
                )
    return units


async def analyze_tender(
    sources: list[TenderSourceDocument], provider: str | None = None
) -> list[RequirementResult]:
    if not sources:
        raise ValueError("Tender has no source documents to analyze.")

    # RC-1 audit finding E1: parsing is synchronous, CPU-bound work (pypdf/
    # openpyxl/xlrd parsing over potentially large files). Run off the
    # event loop via asyncio.to_thread so a single upload can't stall every
    # other concurrent request for the duration of the parse.
    units = await asyncio.to_thread(_build_source_units, sources)
    if not units:
        raise ValueError("No content-bearing source documents found (all attached documents were financial-role or empty).")
    if not any(unit.text.strip() for unit in units):
        raise ValueError(
            "No extractable text found in any attached document (scanned/image-only tenders are "
            "out of scope for M5 — OCR is not applied to tender documents)."
        )

    chunk_size = settings.tender_chunk_page_size
    all_requirements: list[ExtractedRequirement] = []
    unit_lookup: dict[int, SourceUnit] = {}

    client = get_llm_client(provider)

    for chunk_start in range(0, len(units), chunk_size):
        chunk_units = {
            unit_num + 1: units[unit_num]
            for unit_num in range(chunk_start, min(chunk_start + chunk_size, len(units)))
        }
        for unit_num, unit in chunk_units.items():
            unit_lookup[unit_num] = unit

        chunk_pages = {unit_num: unit.text for unit_num, unit in chunk_units.items()}
        user_prompt = tender_requirement.build_prompt(chunk_pages)
        raw_response = await client.complete(
            tender_requirement.SYSTEM_PROMPT, user_prompt, purpose="tender_requirement_extraction"
        )

        extracted_json = parse_json_response(raw_response)
        validated = TenderChunkExtraction.model_validate(extracted_json)
        all_requirements.extend(validated.requirements)

    deduplicated = _deduplicate(all_requirements)
    return [_to_result(req, unit_lookup) for req in deduplicated]


def _deduplicate(requirements: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    """
    Deterministic duplicate removal: exact match on (requirement_type,
    normalized description) — not fuzzy/semantic matching. Keeps the
    first occurrence (lowest source_page). The same requirement can
    legitimately appear verbatim in more than one section of a real
    tender (e.g. a summary section repeating a detailed requirement);
    this only removes true exact duplicates, not similar-but-distinct ones.
    """
    seen: set[tuple[str, str]] = set()
    result = []
    for req in requirements:
        key = (req.requirement_type, (req.description or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(req)
    return result


def _to_result(req: ExtractedRequirement, unit_lookup: dict[int, "SourceUnit"]) -> RequirementResult:
    """
    Confidence from measurable signals, consistent with M3's philosophy
    (never an LLM self-report): whether the source unit actually had
    native text (vs. an empty unit somehow yielding a match — a red
    flag, not a confident result), scaled by field completeness.

    req.source_page is the LLM's reported unit number (still called
    source_page — the [PAGE N] marker/prompt contract is unchanged, see
    module docstring) — resolved back here to real provenance:
    - Unit came from a PDF page: source_page is the real PDF page number
      (backward-compatible with pre-multi-document results), source_location
      is None (the page number alone is sufficient, matching prior behavior).
    - Unit came from a spreadsheet sheet: source_page is None (not a real
      page), source_location carries "Sheet: {name}" instead.
    """
    unit = unit_lookup.get(req.source_page) if req.source_page is not None else None
    unit_ok = unit is not None and bool(unit.text.strip())
    base = 0.95 if unit_ok else 0.3

    fields = [req.requirement_type, req.description, req.source_page]
    populated = sum(1 for f in fields if f not in (None, ""))
    completeness = populated / len(fields)

    confidence = round(base * completeness, 4)

    resolved_page: int | None = None
    source_document_id: uuid.UUID | None = None
    source_location: str | None = None
    if unit is not None:
        source_document_id = unit.document_id
        if unit.label.startswith("Page "):
            try:
                resolved_page = int(unit.label.removeprefix("Page "))
            except ValueError:
                resolved_page = None
        else:
            source_location = unit.label

    return RequirementResult(
        requirement_type=req.requirement_type,
        description=req.description,
        mandatory=req.mandatory,
        source_page=resolved_page,
        source_document_id=source_document_id,
        source_location=source_location,
        confidence=confidence,
        requirement_nature=_resolve_nature(req),
    )
