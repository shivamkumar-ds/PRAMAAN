"""
Schemas the LLM's (or mock's) JSON output must validate against — the
boundary between "what the model said" and "what gets persisted". A
response that fails this validation fails the whole extraction
(Document.processing_status -> FAILED) rather than partially-trusted
data being written.
"""

from pydantic import BaseModel


class CertificationExtraction(BaseModel):
    certification_name: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None  # "YYYY-MM-DD" — parsed to a real date before persisting
    expiry_date: str | None = None


class EmployeeExtraction(BaseModel):
    name: str | None = None
    position: str | None = None
    qualification: str | None = None
    experience: str | None = None
    availability: str | None = None
    skills: list[str] | None = None


class ProjectExtraction(BaseModel):
    client: str | None = None
    industry: str | None = None
    contract_value: float | None = None
    duration: str | None = None
    completion_status: str | None = None
    similarity_tags: list[str] | None = None


class ExtractedRequirement(BaseModel):
    requirement_type: str
    description: str | None = None
    mandatory: bool = False
    source_page: int | None = None
    # Architecture debate Phase 1: only asked of the LLM for requirement_type
    # in {eligibility, technical, certification, experience} (see
    # prompts/tender_requirement.py). None for the three deterministically-
    # classified procedural types, or if the LLM omits/invalidates it --
    # tender_analyzer._resolve_nature() is what turns this raw, possibly-
    # absent value into the final persisted RequirementNature.
    requirement_nature: str | None = None


class TenderChunkExtraction(BaseModel):
    requirements: list[ExtractedRequirement] = []


class DecisionMatchExtraction(BaseModel):
    status: str
    matched_entity_index: int | None = None
    reasoning: str = ""
