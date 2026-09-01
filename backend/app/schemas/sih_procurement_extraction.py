"""
Schema the LLM's JSON output must validate against for procurement
requirement extraction -- same boundary role as app/schemas/sih_extraction.py
(BidderDocument extraction): a response that fails validation fails the
whole extraction (ProcurementDocument.extraction_status -> FAILED)
rather than partially-trusted data being persisted.
"""

from pydantic import BaseModel


class ExtractedRequirement(BaseModel):
    requirement_text: str
    category_hint: str | None = None
    is_mandatory: bool = True


class ProcurementRequirementsExtraction(BaseModel):
    requirements: list[ExtractedRequirement] = []
