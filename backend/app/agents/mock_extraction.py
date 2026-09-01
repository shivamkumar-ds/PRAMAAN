"""
Mock LLM response generator — sandbox verification only (see llm_client.py
for why this exists at all).

Extracts the actual document text embedded in the prompt and pulls out
plausible values via simple "Label: Value" regex matching — the pattern
real certificates, CVs, and project documents commonly use. This is
explicitly NOT simulating language understanding; it's just enough to
prove the surrounding pipeline (parsing -> prompt -> response validation
-> DB write) works against real document text.
"""

import json
import re


def _extract_document_text(user_prompt: str) -> str:
    match = re.search(r'"""\s*(.*?)\s*"""', user_prompt, re.DOTALL)
    return match.group(1) if match else ""


def _find_field(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(rf"{label}\s*[:\-]\s*(.+)", text, re.IGNORECASE)
        if match:
            value = match.group(1).strip().splitlines()[0].strip()
            if value:
                return value
    return None


def _find_date(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(rf"{label}\s*[:\-]\s*(\d{{4}}-\d{{2}}-\d{{2}})", text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _generate_tender_requirements_mock(user_prompt: str) -> str:
    """
    Page-aware pattern matching against [PAGE N] markers — scans line by
    line, tracking the current page, and matches lines that open with a
    recognized requirement-category label. This is genuinely different
    from the single-entity mocks above: it must preserve per-line page
    attribution, not just pull a handful of named fields once.
    """
    full_text = _extract_document_text(user_prompt)

    category_patterns = [
        ("eligibility", r"Eligibility"),
        ("technical", r"Technical Requirement"),
        ("certification", r"Certification(?:\s+Required)?"),
        ("experience", r"Experience"),
        ("evaluation_criteria", r"Evaluation Criteria"),
        ("deadline", r"(?:Submission\s+)?Deadline"),
        ("submission", r"Submission Requirement"),
    ]

    requirements = []
    current_page = None
    for line in full_text.splitlines():
        page_match = re.match(r"\[PAGE (\d+)\]", line.strip())
        if page_match:
            current_page = int(page_match.group(1))
            continue

        for category, label_pattern in category_patterns:
            match = re.match(rf"\s*{label_pattern}\s*[:\-]\s*(.+)", line, re.IGNORECASE)
            if match:
                description = match.group(1).strip()
                mandatory = bool(re.search(r"\b(mandatory|shall|must)\b", line, re.IGNORECASE))
                requirements.append(
                    {
                        "requirement_type": category,
                        "description": description,
                        "mandatory": mandatory,
                        "source_page": current_page,
                    }
                )
                break

    return json.dumps({"requirements": requirements})


def _generate_decision_match_mock(user_prompt: str) -> str:
    """
    Deliberately humble mock behavior, not pretending to real judgment:
    a direct substring match (e.g. a named standard like "ISO 9001"
    appearing in both the requirement and a candidate) returns "met" —
    genuinely findable without real reasoning. Anything requiring actual
    judgment about scale/relevance (experience, technical, eligibility)
    returns "conditional" when *some* relevant candidate exists, rather
    than pretending certainty the mock can't actually deliver. Zero
    candidates always returns "not_met".
    """
    req_match = re.search(r'Requirement:\s*"""\s*(.*?)\s*"""', user_prompt, re.DOTALL)
    requirement_text = req_match.group(1) if req_match else ""

    candidates_match = re.search(
        r'capability records:\s*"""\s*(.*?)\s*"""', user_prompt, re.DOTALL
    )
    candidates_block = candidates_match.group(1) if candidates_match else ""

    if candidates_block.strip() == "(no candidates)" or not candidates_block.strip():
        return json.dumps(
            {"status": "not_met", "matched_entity_index": None, "reasoning": "No candidates provided."}
        )

    candidate_lines = [
        line for line in candidates_block.splitlines() if re.match(r"\[\d+\]", line.strip())
    ]

    # Direct substring match: any word/number sequence shared between the
    # requirement text and a candidate line, length >= 4 chars (avoids
    # matching on trivial short words).
    req_tokens = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9:.\-]{3,}", requirement_text.lower()))
    best_index, best_overlap = None, 0
    for line in candidate_lines:
        index = int(re.match(r"\[(\d+)\]", line.strip()).group(1))
        candidate_tokens = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9:.\-]{3,}", line.lower()))
        overlap = len(req_tokens & candidate_tokens)
        if overlap > best_overlap:
            best_index, best_overlap = index, overlap

    if best_index is not None and best_overlap >= 2:
        return json.dumps(
            {
                "status": "met",
                "matched_entity_index": best_index,
                "reasoning": f"Direct match found against candidate [{best_index}] "
                f"({best_overlap} shared identifying terms).",
            }
        )

    # Some candidates exist in the relevant domain, but no confident
    # direct match — genuinely uncertain, not a confident "not_met".
    return json.dumps(
        {
            "status": "conditional",
            "matched_entity_index": 0 if candidate_lines else None,
            "reasoning": "Relevant company records exist but automated matching cannot "
            "confidently confirm they satisfy this requirement's specific scale or scope — "
            "human review recommended.",
        }
    )


# Keyword -> category_hint mapping for the mock procurement-requirement
# extractor below, checked in this order (most specific first) so a line
# mentioning several terms at once still gets one sensible hint rather
# than the first alphabetically-registered category. Deliberately the
# same closed vocabulary procurement_requirements.KNOWN_CATEGORY_CODES
# declares -- kept as a local literal (not imported) for the same
# "prompts/mocks have no DB-layer import" reason procurement_requirements.py
# itself gives.
_PROCUREMENT_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("blacklisting", ["blacklist", "debar"]),
    ("udyam", ["udyam", "msme", "udyog aadhaar"]),
    ("gst", ["gstin", "gst registration", "goods and services tax"]),
    ("pan_itr", ["income tax return", "itr filing", "permanent account number", " pan "]),
    ("mca21", ["cin", "certificate of incorporation", "mca21", "corporate registration"]),
    ("epfo", ["epfo", "provident fund"]),
    ("esic", ["esic", "employees' state insurance", "employees state insurance"]),
    ("startup_india", ["startup india", "dpiit"]),
    ("nsic", ["nsic"]),
    ("oem_authorization", ["oem authorization", "manufacturer authorization", "authorised dealer"]),
    ("digilocker", ["digilocker"]),
    ("make_in_india", ["make in india", "local content"]),
]

# Lines with none of the category keywords above are still real
# eligibility requirements in the mock's demo documents (turnover, years
# of experience) -- included with category_hint None, exactly matching
# what the real prompt asks the model to do for a requirement with no
# registry-backed check.
_UNCATEGORIZED_ELIGIBILITY_KEYWORDS = ["turnover", "years of experience", "similar work", "annual turnover"]


def _generate_procurement_requirements_mock(user_prompt: str) -> str:
    """
    Line-by-line keyword scan over the document text embedded in the
    prompt -- same "genuinely exercise the pipeline against real
    (if synthetic) document text" philosophy as every other mock in this
    module, not a fantasy response. A line is treated as one requirement
    if it contains any recognized eligibility/compliance keyword; its
    category_hint is the first matching category in
    _PROCUREMENT_CATEGORY_KEYWORDS (or None for the uncategorized
    eligibility keywords), and is_mandatory reflects whether the line
    itself contains mandatory-sounding language ("shall"/"must"/
    "mandatory"/"required") -- defaulting True otherwise, matching the
    real prompt's "true unless clearly marked optional" instruction.
    """
    text = _extract_document_text(user_prompt)
    requirements = []
    seen_texts = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or re.match(r"^\[PAGE \d+\]", line):
            continue
        lowered = line.lower()

        category_hint = None
        for code, keywords in _PROCUREMENT_CATEGORY_KEYWORDS:
            if any(kw in lowered for kw in keywords):
                category_hint = code
                break

        if category_hint is None and not any(kw in lowered for kw in _UNCATEGORIZED_ELIGIBILITY_KEYWORDS):
            continue

        requirement_text = line.lstrip("-•*").strip()
        if not requirement_text or requirement_text in seen_texts:
            continue
        seen_texts.add(requirement_text)

        is_mandatory = True
        if re.search(r"\b(optional|preferred|desirable)\b", lowered):
            is_mandatory = False

        requirements.append(
            {
                "requirement_text": requirement_text,
                "category_hint": category_hint,
                "is_mandatory": is_mandatory,
            }
        )

    return json.dumps({"requirements": requirements})


def generate_mock_response(system_prompt: str, user_prompt: str) -> str:
    text = _extract_document_text(user_prompt)

    if "REQUIREMENT MATCHING" in system_prompt:
        return _generate_decision_match_mock(user_prompt)

    if "PROCUREMENT ELIGIBILITY REQUIREMENTS" in system_prompt:
        return _generate_procurement_requirements_mock(user_prompt)

    if "TENDER REQUIREMENTS" in system_prompt:
        return _generate_tender_requirements_mock(user_prompt)

    if "CERTIFICATION document" in system_prompt:
        result = {
            "certification_name": _find_field(text, r"Certificate(?:\s+Name)?", "Certification"),
            "issuing_authority": _find_field(text, "Issuing Authority", "Issued By"),
            "issue_date": _find_date(text, "Issue Date"),
            "expiry_date": _find_date(text, "Expiry Date", "Valid Until"),
        }
    elif "EMPLOYEE CV document" in system_prompt:
        skills_raw = _find_field(text, "Skills")
        result = {
            "name": _find_field(text, "Name"),
            "position": _find_field(text, "Position"),
            "qualification": _find_field(text, "Qualification"),
            "experience": _find_field(text, "Experience"),
            "availability": _find_field(text, "Availability"),
            "skills": [s.strip() for s in skills_raw.split(",")] if skills_raw else None,
        }
    elif "PROJECT COMPLETION document" in system_prompt:
        tags_raw = _find_field(text, "Tags", "Similarity Tags")
        value_raw = _find_field(text, "Contract Value")
        contract_value = None
        if value_raw:
            digits = re.sub(r"[^\d.]", "", value_raw)
            contract_value = float(digits) if digits else None
        result = {
            "client": _find_field(text, "Client"),
            "industry": _find_field(text, "Industry"),
            "contract_value": contract_value,
            "duration": _find_field(text, "Duration"),
            "completion_status": _find_field(text, "Completion Status", "Status"),
            "similarity_tags": [t.strip() for t in tags_raw.split(",")] if tags_raw else None,
        }
    else:
        result = {}

    return json.dumps(result)
