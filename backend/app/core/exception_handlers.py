"""
Centralized service-exception -> HTTP response mapping (Phase 1.5 findings
#4 and #5).

Before this, every router repeated the identical `except NotFoundError:
raise HTTPException(404, ...)` block by hand (~30 occurrences across 9
routers, verified 1:1 consistent), and none of them logged before
translating -- LLM-path failures were logged, everything else (404s,
409s, validation failures) left no trace. Registering these once here
does both at the same time: the mapping is now enforced structurally
(a router can't forget to catch something), and every non-2xx service
exception gets exactly one log line before becoming a response.

Routers no longer need `try/except NotFoundError/ConflictError/...`
blocks for these types -- letting the exception propagate is sufficient;
FastAPI dispatches it to the matching handler below. A router should
still catch one of these locally only if it needs to do something extra
on the way out (e.g. resolving verifier names before returning), never
just to translate to an HTTP status.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    AuthenticationError,
    ConflictError,
    ExtractionError,
    FileTooLargeError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.services.sih.officer_decision_service import InvalidDecisionError

logger = logging.getLogger(__name__)

# (exception type, HTTP status code, log level) -- the exact mapping every
# router already implemented by hand, confirmed identical at every call
# site before centralizing it here.
_EXCEPTION_STATUS_MAP: list[tuple[type[Exception], int]] = [
    (NotFoundError, 404),
    (ConflictError, 409),
    (ExtractionError, 422),
    (UnsupportedFileTypeError, 415),
    (FileTooLargeError, 413),
    (AuthenticationError, 401),
    # SIH26100 (Phase 2) -- a blank note or an invalid decision value is a
    # client input error, same tier as ExtractionError above.
    (InvalidDecisionError, 422),
]


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type, status_code in _EXCEPTION_STATUS_MAP:

        def _make_handler(status_code: int):
            async def _handler(request: Request, exc: Exception) -> JSONResponse:
                # 401/404 are routine (auth/lookup misses); 409/413/415/422
                # are also expected-domain outcomes, not bugs -- log at
                # INFO/WARNING, not ERROR, so real incidents (5xxs, unhandled
                # exceptions) still stand out in the logs.
                logger.warning(
                    "%s %s -> %d: %s",
                    request.method,
                    request.url.path,
                    status_code,
                    exc,
                )
                return JSONResponse(status_code=status_code, content={"detail": str(exc)})

            return _handler

        app.add_exception_handler(exc_type, _make_handler(status_code))
