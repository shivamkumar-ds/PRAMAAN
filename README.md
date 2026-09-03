# BidOps

## Live Demo

- **App:** [parmaan-chi.vercel.app](https://parmaan-chi.vercel.app/)
- **Login:** `admin@test.in` / `password`
- **Demo video:** [Watch on Google Drive](https://drive.google.com/file/d/1_mB4YNETORpYcEpJO48OMBsl4SranAKF/view?usp=sharing)

> Demo credentials only — for evaluation purposes, not a production account.

Enterprise procurement decision-intelligence platform. Reads a tender, cross-references it
against an organization's own capability evidence, and returns a structured, evidence-backed
Proceed / Do Not Proceed / Conditional recommendation — not a document summary, not a chat
transcript.

This is **BidOps_Final**, the single canonical codebase. There is no separate Vertex, OpenAI,
Qwen, or Hackathon edition — see `docs/ENGINEERING_DIRECTIVE.md` for why, and
`backend/99_DECISIONS_LOG.md` (entry D-143) for exactly how this repository was consolidated
from its two prior lineages.

## Structure

- `backend/` — FastAPI + PostgreSQL. See `backend/README.md` for setup, configuration, and
  the full request-to-recommendation workflow.
- `frontend/` — React + TypeScript + Vite. Dashboard, Documents, Capabilities, Tender
  Workspace, Reports.
- `docs/` — the frozen product/architecture specification (`00_Project_Context.md` through
  `11_Risk_Assessment.md`), the engineering `CONSTITUTION.md`, and
  `ENGINEERING_DIRECTIVE.md` (the standing founder-to-engineering direction for this
  project).
- `BACKLOG.md` — real, open, unresolved product/engineering items — not a wishlist, a record
  of what's actually still missing.

## Where things stand

- **OpenAI** — operational reference implementation. Verified end-to-end, including the
  Decision Engine.
- **Vertex AI (Gemini)** — strategic long-term provider. Implemented and offline-tested;
  real on-GCP verification is deployment-gated (needs `gcloud`/ADC and network access no
  development sandbox in this project's history has had).
- **Qwen** — frozen. DashScope is unreachable for new accounts from every region tried so
  far; kept working, not deleted.

See `backend/99_DECISIONS_LOG.md` for the complete reasoning trail behind every decision in
this repository, in order — the actual source of truth for *why*, not just *what*.

## Handing off or exporting this repository

Never zip or copy the working directory directly for a hand-off, review, or support request —
`backend/.env` and `frontend/.env` are gitignored (never committed), but a plain directory zip
includes them anyway, since they're still real files on disk. This is exactly how a real
credential was exposed during the RC-2 engineering audit (see `docs/RC2_FINAL_ENGINEERING_AUDIT.pdf`,
finding C-1).

Use `./scripts/safe_export.sh` instead. It exports via `git archive`, which can only ever include
what git is actually tracking — `.env` files, `venv/`, `node_modules/`, and local build output are
structurally excluded, not just excluded if someone remembers the right flags.
