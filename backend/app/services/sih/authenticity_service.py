"""
Authenticity Scanner -- SIH26100 minimal-real engine (Phase 2 of the
governing directive).

Inspects the ACTUAL stored bytes of a BidderDocument (via
app.core.storage.local_file_for_read, the same seam every other parser
in this codebase already uses -- no second file-storage path) and
returns a small set of explainable, named indicators. Deliberately
narrow, per the brief: PDF metadata consistency (pypdf), OOXML
(.docx/.xlsx) core-properties consistency (stdlib zipfile + ElementTree),
and image metadata consistency (Pillow: EXIF for JPEG, text chunks for
PNG) only -- no pixel-level forensics, no Error Level Analysis, no ML
tamper classifier. This is explainable metadata inspection, not forensic
authentication, and every indicator and summary label is worded to never
claim a document is "genuine" or "forged" -- only what was and wasn't
observed in its metadata. An officer is always the one who decides what
an indicator means for their decision.

.docx/.xlsx are OOXML -- both are zip archives that (when produced by a
compliant tool) contain docProps/core.xml (creator, lastModifiedBy,
created, modified) and docProps/app.xml (the producing Application name,
e.g. "Microsoft Excel", "Google Sheets", "LibreOffice"). Parsed with
Python's stdlib zipfile + xml.etree.ElementTree -- no new dependency;
this project has no defusedxml pin (see requirements.txt), and these are
the officer's own uploaded files already passing through
storage.validate_file_type()'s extension/content-type allowlist, the
same trust boundary every other parser in this codebase (pypdf, Pillow,
python-docx) already operates inside. A malformed or non-conformant zip/
XML is treated as a reportable finding (see _scan_ooxml's except clause),
never an unhandled crash.

summary_label is one of a small closed vocabulary:
  - "no_anomalies_detected": scan ran, nothing above "info" severity found.
  - "indicators_present": scan ran, at least one "low"/"medium"/"high"
    severity indicator found -- worth an officer's attention, never
    itself a verdict.
  - "not_analyzable": the file type has no metadata-analysis path here
    (currently only legacy .xls, the pre-OOXML binary format) --
    honestly reported as such, never silently skipped or defaulted to
    "clean".

Persisted insert-only into AuthenticityScan (app/models/sih/document.py),
mirroring VerificationResult -- a document's scan history is preserved
across re-scans.
"""

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import storage
from app.models.sih.document import AuthenticityScan, BidderDocument
from app.services.sih import document_service

# Severities are ordered informational -> attention-worthy; only "low",
# "medium", "high" push summary_label to "indicators_present". "info" is
# a plain observed fact (e.g. "this PDF has embedded metadata"), never
# itself a signal of anything.
_ATTENTION_SEVERITIES = {"low", "medium", "high"}

_ANALYZABLE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx"}
_OOXML_EXTENSIONS = {".docx", ".xlsx"}

# Software tags that commonly indicate a document was produced by a
# general-purpose image/photo editor rather than a scanner, camera, or
# office/PDF-producing application -- an observation worth surfacing,
# never proof of tampering (legitimate scans are sometimes touched up).
_EDITING_SOFTWARE_KEYWORDS = ("photoshop", "gimp", "paint.net", "affinity photo")


@dataclass
class AuthenticityIndicator:
    code: str
    label: str
    detail: str
    severity: str  # "info" | "low" | "medium" | "high"


def scan_document(
    db: Session,
    submission_id: uuid.UUID,
    document_id: uuid.UUID,
    company_id: uuid.UUID,
    scanned_by: uuid.UUID,
) -> AuthenticityScan:
    """
    Runs an authenticity scan against a BidderDocument's actual stored
    file and persists the result. Ownership is resolved exactly like
    every other document-scoped operation (document_service.get_owned_document),
    so a scan can never be run against a document outside the caller's
    own company.
    """
    document = document_service.get_owned_document(db, submission_id, document_id, company_id)
    extension = Path(document.storage_path).suffix.lower()

    if extension not in _ANALYZABLE_EXTENSIONS:
        indicators = [
            AuthenticityIndicator(
                code="unsupported_format",
                label="Format not supported for authenticity analysis",
                detail=(
                    f"'{extension}' files have no metadata-analysis path in this prototype "
                    "(only PDF and image files do). This is not a finding either way."
                ),
                severity="info",
            )
        ]
        summary_label = "not_analyzable"
    else:
        with storage.local_file_for_read(document.storage_path) as file_path:
            if extension == ".pdf":
                indicators = _scan_pdf(file_path)
            elif extension in _OOXML_EXTENSIONS:
                indicators = _scan_ooxml(file_path)
            else:
                indicators = _scan_image(file_path)
        summary_label = (
            "indicators_present"
            if any(i.severity in _ATTENTION_SEVERITIES for i in indicators)
            else "no_anomalies_detected"
        )

    scan = AuthenticityScan(
        document_id=document_id,
        indicators=[asdict(i) for i in indicators],
        summary_label=summary_label,
        scanned_by=scanned_by,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def get_latest_scan(db: Session, document_id: uuid.UUID) -> AuthenticityScan | None:
    """Most recent scan for a document, or None if it's never been scanned --
    insert-only history, same pattern as verification_service.get_latest_results()."""
    return (
        db.query(AuthenticityScan)
        .filter(AuthenticityScan.document_id == document_id)
        .order_by(AuthenticityScan.scanned_at.desc())
        .first()
    )


def list_scans(db: Session, document_id: uuid.UUID) -> list[AuthenticityScan]:
    return (
        db.query(AuthenticityScan)
        .filter(AuthenticityScan.document_id == document_id)
        .order_by(AuthenticityScan.scanned_at.desc())
        .all()
    )


def _scan_pdf(file_path: Path) -> list[AuthenticityIndicator]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    indicators: list[AuthenticityIndicator] = []
    try:
        reader = PdfReader(str(file_path))
    except (PdfReadError, Exception) as exc:  # noqa: BLE001 -- any parse failure is itself the finding
        return [
            AuthenticityIndicator(
                code="unreadable_pdf",
                label="PDF could not be parsed",
                detail=f"The file could not be read as a valid PDF ({exc}). This alone can indicate "
                "corruption or a non-standard file, not necessarily tampering.",
                severity="medium",
            )
        ]

    if reader.is_encrypted:
        indicators.append(
            AuthenticityIndicator(
                code="encrypted_pdf",
                label="PDF is encrypted",
                detail="The file is password-protected/encrypted at the PDF level.",
                severity="info",
            )
        )

    page_count = len(reader.pages)
    if page_count == 0:
        indicators.append(
            AuthenticityIndicator(
                code="zero_pages",
                label="PDF has no pages",
                detail="The document contains zero pages, which is not a normal, usable certificate/document.",
                severity="medium",
            )
        )

    info = reader.metadata
    producer = (info.producer if info else None) or None
    creator = (info.creator if info else None) or None
    creation_date = (info.creation_date if info else None) or None
    mod_date = (info.modification_date if info else None) or None

    if not info or (not producer and not creator and not creation_date and not mod_date):
        indicators.append(
            AuthenticityIndicator(
                code="no_metadata",
                label="No embedded document metadata",
                detail="No Producer/Creator/creation or modification dates were found in the PDF's metadata. "
                "Common for scanned documents and not inherently suspicious on its own -- it just means "
                "there is nothing here to cross-check.",
                severity="low",
            )
        )
    else:
        indicators.append(
            AuthenticityIndicator(
                code="metadata_summary",
                label="Embedded document metadata",
                detail=(
                    f"Producer: {producer or '—'} · Creator: {creator or '—'} · "
                    f"Created: {creation_date.isoformat() if creation_date else '—'} · "
                    f"Modified: {mod_date.isoformat() if mod_date else '—'}"
                ),
                severity="info",
            )
        )
        if creation_date and mod_date and mod_date < creation_date:
            indicators.append(
                AuthenticityIndicator(
                    code="modification_before_creation",
                    label="Modification date precedes creation date",
                    detail=(
                        f"The PDF's recorded modification date ({mod_date.isoformat()}) is earlier than its "
                        f"recorded creation date ({creation_date.isoformat()}) -- internally inconsistent "
                        "metadata, which can happen with certain editing tools or a manually altered file."
                    ),
                    severity="medium",
                )
            )
        producer_or_creator = f"{producer or ''} {creator or ''}".lower()
        if any(keyword in producer_or_creator for keyword in _EDITING_SOFTWARE_KEYWORDS):
            indicators.append(
                AuthenticityIndicator(
                    code="editing_software_producer",
                    label="Produced by a general-purpose image/photo editor",
                    detail=(
                        f"The PDF's Producer/Creator metadata references image-editing software "
                        f"('{producer or creator}'), rather than a scanner, office suite, or PDF generator. "
                        "This is an observation worth a closer look, not proof of alteration -- some "
                        "legitimate documents are legitimately touched up before submission."
                    ),
                    severity="medium",
                )
            )

    return indicators


_OOXML_CORE_NS = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
_OOXML_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_OOXML_DCTERMS_NS = "{http://purl.org/dc/terms/}"
_OOXML_EXTENDED_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"


def _scan_ooxml(file_path: Path) -> list[AuthenticityIndicator]:
    import zipfile
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(file_path) as archive:
            core_xml = archive.read("docProps/core.xml") if "docProps/core.xml" in archive.namelist() else None
            app_xml = archive.read("docProps/app.xml") if "docProps/app.xml" in archive.namelist() else None
    except zipfile.BadZipFile as exc:
        return [
            AuthenticityIndicator(
                code="unreadable_ooxml",
                label="File could not be parsed",
                detail=f"The file could not be read as a valid Office Open XML (.docx/.xlsx) archive ({exc}). "
                "This alone can indicate corruption or a non-standard file, not necessarily tampering.",
                severity="medium",
            )
        ]

    if core_xml is None and app_xml is None:
        return [
            AuthenticityIndicator(
                code="no_metadata",
                label="No embedded document metadata",
                detail="No docProps/core.xml or docProps/app.xml were found in this file -- common for "
                "files produced or re-saved by tools that strip metadata, and not inherently suspicious "
                "on its own. There is just nothing here to cross-check.",
                severity="low",
            )
        ]

    creator = last_modified_by = created_raw = modified_raw = None
    if core_xml is not None:
        try:
            core_root = ElementTree.fromstring(core_xml)
            creator = _ooxml_text(core_root, f"{_OOXML_DC_NS}creator")
            last_modified_by = _ooxml_text(core_root, f"{_OOXML_CORE_NS}lastModifiedBy")
            created_raw = _ooxml_text(core_root, f"{_OOXML_DCTERMS_NS}created")
            modified_raw = _ooxml_text(core_root, f"{_OOXML_DCTERMS_NS}modified")
        except ElementTree.ParseError as exc:
            return [
                AuthenticityIndicator(
                    code="unreadable_ooxml",
                    label="Document metadata could not be parsed",
                    detail=f"docProps/core.xml exists but is not valid XML ({exc}) -- internally "
                    "inconsistent, which can happen with a corrupted or manually altered file.",
                    severity="medium",
                )
            ]

    application = None
    if app_xml is not None:
        try:
            app_root = ElementTree.fromstring(app_xml)
            application = _ooxml_text(app_root, f"{_OOXML_EXTENDED_NS}Application")
        except ElementTree.ParseError:
            # app.xml is the less critical of the two files (Application
            # name only) -- a parse failure here doesn't block reporting
            # whatever core.xml already yielded above.
            pass

    indicators = [
        AuthenticityIndicator(
            code="metadata_summary",
            label="Embedded document metadata",
            detail=(
                f"Creator: {creator or '—'} · Last modified by: {last_modified_by or '—'} · "
                f"Created: {created_raw or '—'} · Modified: {modified_raw or '—'} · "
                f"Application: {application or '—'}"
            ),
            severity="info",
        )
    ]

    created_dt = _parse_ooxml_datetime(created_raw)
    modified_dt = _parse_ooxml_datetime(modified_raw)
    if created_dt is not None and modified_dt is not None and modified_dt < created_dt:
        indicators.append(
            AuthenticityIndicator(
                code="modification_before_creation",
                label="Modification date precedes creation date",
                detail=(
                    f"The document's recorded modification date ({modified_raw}) is earlier than its "
                    f"recorded creation date ({created_raw}) -- internally inconsistent metadata, which "
                    "can happen with certain editing tools or a manually altered file."
                ),
                severity="medium",
            )
        )

    if creator and last_modified_by and creator.strip().lower() != last_modified_by.strip().lower():
        indicators.append(
            AuthenticityIndicator(
                code="creator_last_modified_by_mismatch",
                label="Created and last saved by different people",
                detail=(
                    f"This document's Creator ('{creator}') and Last modified by ('{last_modified_by}') "
                    "metadata fields name different people -- an observation worth a closer look (a "
                    "document changing hands during drafting/review is often entirely legitimate), never "
                    "proof of alteration on its own."
                ),
                severity="low",
            )
        )

    if application and any(keyword in application.lower() for keyword in _EDITING_SOFTWARE_KEYWORDS):
        indicators.append(
            AuthenticityIndicator(
                code="editing_software_producer",
                label="Produced by a general-purpose image/photo editor",
                detail=(
                    f"This document's Application metadata references image-editing software "
                    f"('{application}') rather than an office suite -- worth a closer look, not proof "
                    "of alteration."
                ),
                severity="medium",
            )
        )

    return indicators


def _ooxml_text(root, tag: str) -> str | None:
    element = root.find(tag)
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _parse_ooxml_datetime(raw: str | None):
    """OOXML core-properties dates are ISO-8601 (dcterms:W3CDTF, typically
    '2024-01-15T10:30:00Z') -- parsed defensively since this is
    officer-uploaded, not schema-validated, content; an unparseable value
    is simply excluded from the modified-before-created comparison rather
    than raising, exactly like the PDF scanner's pypdf-provided dates
    (already datetime objects there, never a raw string to fail on)."""
    if not raw:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _scan_image(file_path: Path) -> list[AuthenticityIndicator]:
    from PIL import Image
    from PIL.ExifTags import TAGS

    indicators: list[AuthenticityIndicator] = []
    try:
        image = Image.open(file_path)
        image.load()
    except Exception as exc:  # noqa: BLE001 -- any parse failure is itself the finding
        return [
            AuthenticityIndicator(
                code="unreadable_image",
                label="Image could not be parsed",
                detail=f"The file could not be read as a valid image ({exc}).",
                severity="medium",
            )
        ]

    indicators.append(
        AuthenticityIndicator(
            code="image_summary",
            label="Image properties",
            detail=f"Format: {image.format} · Size: {image.width}x{image.height}px · Mode: {image.mode}",
            severity="info",
        )
    )

    if image.format == "PNG":
        return indicators + _png_text_chunk_indicators(image)

    if image.format != "JPEG":
        # Any other format Pillow can open but this scanner doesn't have
        # a specific metadata check for -- reported via image_summary
        # above only, no format-specific checks run.
        return indicators

    exif = image.getexif()
    if not exif:
        indicators.append(
            AuthenticityIndicator(
                code="no_exif_data",
                label="No EXIF metadata",
                detail="This JPEG carries no EXIF metadata (camera/software/date information). Common for "
                "a screenshot, a re-saved/converted image, or a scan -- not inherently suspicious on its "
                "own, but there is nothing here to cross-check.",
                severity="low",
            )
        )
        return indicators

    exif_tags = {TAGS.get(tag_id, tag_id): value for tag_id, value in exif.items()}
    software = str(exif_tags.get("Software", "")).strip()
    make = str(exif_tags.get("Make", "")).strip()
    model = str(exif_tags.get("Model", "")).strip()

    indicators.append(
        AuthenticityIndicator(
            code="exif_summary",
            label="EXIF metadata present",
            detail=f"Software: {software or '—'} · Camera make/model: {(make + ' ' + model).strip() or '—'}",
            severity="info",
        )
    )
    if software and any(keyword in software.lower() for keyword in _EDITING_SOFTWARE_KEYWORDS):
        indicators.append(
            AuthenticityIndicator(
                code="editing_software_exif",
                label="EXIF Software tag names an image editor",
                detail=(
                    f"This image's EXIF Software tag is '{software}', a general-purpose photo editor "
                    "rather than a camera or scanner. This is an observation worth a closer look, not "
                    "proof of alteration."
                ),
                severity="medium",
            )
        )

    return indicators


def _png_text_chunk_indicators(image) -> list[AuthenticityIndicator]:
    """
    PNG carries no EXIF -- Pillow instead exposes any tEXt/iTXt/zTXt
    ancillary chunks via image.text / image.info. Many legitimate PNGs
    (especially scans and screenshots) have none at all -- that is a
    legitimate "no metadata signal available" result, reported as an
    "info"-severity observation, never treated as itself suspicious or
    as a failure to find something that should be there.
    """
    text_chunks: dict = getattr(image, "text", None) or {}
    if not text_chunks:
        return [
            AuthenticityIndicator(
                code="no_png_text_metadata",
                label="No PNG text metadata",
                detail="This PNG carries no tEXt/iTXt/zTXt metadata chunks (e.g. a Software tag). Common "
                "for a screenshot, scan, or re-saved/converted image -- not inherently suspicious on its "
                "own, but there is nothing here to cross-check.",
                severity="info",
            )
        ]

    software = str(text_chunks.get("Software", "")).strip()
    indicators = [
        AuthenticityIndicator(
            code="png_text_summary",
            label="PNG text metadata present",
            detail=f"Software: {software or '—'} · Other tags: "
            f"{', '.join(k for k in text_chunks if k != 'Software') or '—'}",
            severity="info",
        )
    ]
    if software and any(keyword in software.lower() for keyword in _EDITING_SOFTWARE_KEYWORDS):
        indicators.append(
            AuthenticityIndicator(
                code="editing_software_png",
                label="PNG Software tag names an image editor",
                detail=(
                    f"This image's PNG Software tag is '{software}', a general-purpose photo editor "
                    "rather than a camera or scanner. This is an observation worth a closer look, not "
                    "proof of alteration."
                ),
                severity="medium",
            )
        )
    return indicators
