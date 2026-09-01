"""
Procurement Requirement Extraction Agent -- Requirement-to-Evidence
Mapping engine.

Structurally identical to app/agents/sih_document_extractor.py: parses a
document, builds the prompt, calls the existing LLM client abstraction
(app/agents/llm_client.get_llm_client(), never a second provider
integration), validates the response against a Pydantic schema, and
returns a plain result the service layer persists. Never touches the
database directly.

Unlike sih_document_extractor, there is no per-category prompt/schema
selection here -- one document, one prompt, one call, returning a list
of requirements (each carrying its own optional category_hint) rather
than a single category's structured fields.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.agents.document_parser import extract_text
from app.agents.json_utils import parse_json_response
from app.agents.llm_client import get_llm_client
from app.agents.prompts import procurement_requirements
from app.schemas.sih_procurement_extraction import ExtractedRequirement, ProcurementRequirementsExtraction


@dataclass
class ProcurementRequirementExtractionResult:
    requirements: list[ExtractedRequirement]
    used_ocr: bool


async def extract_procurement_requirements(file_path: Path, extension: str) -> ProcurementRequirementExtractionResult:
    parsed = await asyncio.to_thread(extract_text, file_path, extension)
    if not parsed.text.strip():
        raise ValueError(
            "No extractable text found in document (parsing and OCR both produced empty output)."
        )

    user_prompt = procurement_requirements.build_prompt(parsed.text)
    client = get_llm_client()
    raw_response = await client.complete(
        procurement_requirements.SYSTEM_PROMPT, user_prompt, purpose="procurement_requirement_extraction"
    )

    extracted_json = parse_json_response(raw_response)
    validated = ProcurementRequirementsExtraction.model_validate(extracted_json)

    # Constrain category_hint to the known list defensively even though
    # the prompt already asks for this -- an LLM (or the deterministic
    # mock) may still return a value outside the closed set, and a
    # requirement mis-mapped to a nonexistent category would silently
    # never match anything in get_requirement_evidence_map(). Never
    # forced to a guess: an out-of-set value is honestly downgraded to
    # null (no_automated_check), the same outcome as the model
    # returning null itself.
    known = set(procurement_requirements.KNOWN_CATEGORY_CODES)
    requirements = [
        req if req.category_hint in known else req.model_copy(update={"category_hint": None})
        for req in validated.requirements
    ]

    return ProcurementRequirementExtractionResult(requirements=requirements, used_ocr=parsed.used_ocr)
