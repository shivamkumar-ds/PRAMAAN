"""
SIH26100 -- Bidder Verification services.

Structurally mirrors BidOps' existing services/ layer (one module per
concern, domain-level exceptions raised from app.services.exceptions,
never HTTPException) but operates entirely on the new sibling domain in
app/models/sih/ -- never on Tender/Requirement/Capability. No routers
exist yet in Phase 1 (see the Phase 1 report for scope).
"""
