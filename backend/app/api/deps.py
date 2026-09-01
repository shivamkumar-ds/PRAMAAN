"""
Shared API-layer dependencies — authentication and RBAC.

Kept in the API layer, not services, since they deal with an HTTP-specific
concern (the Authorization header) even though they call into the User
model for the actual lookup.
"""

from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User
from app.models.enums import UserRole, UserStatus

# auto_error=False: by default, HTTPBearer raises its own 403 "Not
# authenticated" when the Authorization header is entirely missing —
# semantically wrong (401 means "authenticate"; 403 means "you did,
# but you're not allowed") and inconsistent with the 401 this same
# dependency returns for a present-but-invalid token. Disabling
# auto_error and handling the missing-header case explicitly below
# makes both cases return 401 uniformly.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Strict authentication — 401 for a missing, invalid, or expired
    token, or for a valid token belonging to a user who no longer exists
    or is inactive.

    Status is re-checked from the database on every request rather than
    trusted from the token, so deactivating a user takes effect
    immediately rather than only once their existing token expires.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception

    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise credentials_exception
    return user


def require_administrator(current_user: User = Depends(get_current_user)) -> User:
    """Authorization on top of authentication — the caller must specifically be an Administrator."""
    if current_user.role != UserRole.ADMINISTRATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Administrator role.",
        )
    return current_user


def require_approver(current_user: User = Depends(get_current_user)) -> User:
    """
    Authorization for per-Verdict compliance-row overrides. Executive is
    the intended production approver (per the PRD's role definitions);
    Administrator is also allowed so a newly registered company can
    complete the full workflow without first creating a separate
    Executive user — a deliberate bootstrap/MVP allowance, not an
    oversight.
    """
    if current_user.role not in (UserRole.EXECUTIVE, UserRole.ADMINISTRATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Executive or Administrator role.",
        )
    return current_user


_SIH_DECISION_ROLES = (UserRole.ADMINISTRATOR, UserRole.EXECUTIVE, UserRole.REVIEWER, UserRole.BID_MANAGER)


def require_sih_decision_role(current_user: User = Depends(get_current_user)) -> User:
    """
    Authorization for SIH26100's officer-decision-recording endpoint
    (POST /sih/submissions/{id}/decision) -- additive to the blanket
    require_administrator gate every other SIH write endpoint originally
    used (see app/api/v1/sih.py's module docstring: no dedicated
    "Procurement Officer" role exists, so Phase 2 mapped every SIH write
    to Administrator as the smallest-safe default, flagged as
    revisitable). REVIEWER and BID_MANAGER are the two existing UserRole
    values whose real-world job (reviewing a bidder's compliance findings
    and calling approve/reject/request-clarification) matches this
    specific action, per the PRD's role definitions. EXECUTIVE was added
    alongside the full 5-role RBAC pass (require_sih_write_role /
    require_sih_award_role below) -- the PRD's role definitions put
    Executive at least as senior as Administrator for every SIH action,
    so an Executive being unable to record a decision while an
    Administrator can was a gap, not an intentional restriction.
    Administrator is kept, never removed, so every change here has been
    purely additive.
    """
    if current_user.role not in _SIH_DECISION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Administrator, Executive, Reviewer, or Bid Manager role.",
        )
    return current_user


def require_sih_write_role(current_user: User = Depends(get_current_user)) -> User:
    """
    Authorization for the day-to-day SIH26100 evidence-gathering write
    endpoints -- upload/extract/confirm a bidder document, run
    verification (manual or document-driven), upload a tender/requirement
    document, create/update a procurement/bidder/submission. The one rule
    that must be airtight here is that AUDITOR is excluded: "read-only
    auditor" is the entire point of that role existing (per the PRD's
    role definitions), and before this function existed most of these
    endpoints only required get_current_user (any authenticated user),
    which let an Auditor call them -- that gap is what this closes.
    Every other role (ADMINISTRATOR, EXECUTIVE, REVIEWER, BID_MANAGER) is
    deliberately allowed -- conservative-by-default per the governing
    brief: where a finer-grained split isn't clearly called for, prefer
    not locking out a role that legitimately needs the action.
    Setting a Procurement's awarded bidder is the one action carved out
    of this and gated separately by require_sih_award_role, since award
    decisions are Administrator/Executive-only by design (see
    app/services/sih/collusion_radar_service.py's repeat-winner
    indicator, which depends on awarded_bidder_id being set responsibly).
    """
    if current_user.role == UserRole.AUDITOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditors have read-only access to SIH26100 data and cannot perform this action.",
        )
    return current_user


_SIH_AWARD_ROLES = (UserRole.ADMINISTRATOR, UserRole.EXECUTIVE)


def require_sih_award_role(current_user: User = Depends(get_current_user)) -> User:
    """
    Authorization for setting a Procurement's awarded bidder
    (PATCH /sih/procurements/{id}/award) -- narrower than
    require_sih_write_role: recording who won a procurement is a
    consequential, officer-facing business decision (and directly feeds
    the Collusion Radar's repeated-winner indicator), not day-to-day
    evidence-gathering, so it's scoped to Administrator/Executive only,
    mirroring require_business_decision_permission's role set above.
    """
    if current_user.role not in _SIH_AWARD_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the Administrator or Executive role.",
        )
    return current_user


# Permission-shaped authorization for the Bid Decision feature
# (docs/BID_DECISION_DESIGN.md §7). There is no permissions table in
# this schema yet, so the permission is backed today by the same flat
# role check as require_approver — but every caller depends on the
# named permission function below, never on the role comparison
# directly. Introducing a real can_make_business_decision permissions
# table later is then a one-function change: nothing at any call site
# (routers, tests) needs to know the difference.
_BUSINESS_DECISION_ROLES = (UserRole.EXECUTIVE, UserRole.ADMINISTRATOR)


def user_can_make_business_decision(user: User) -> bool:
    """The `can_make_business_decision` permission, as a plain predicate."""
    return user.role in _BUSINESS_DECISION_ROLES


def require_business_decision_permission(current_user: User = Depends(get_current_user)) -> User:
    """Authorization for recording a Business Decision on a mission."""
    if not user_can_make_business_decision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to record a business decision.",
        )
    return current_user
