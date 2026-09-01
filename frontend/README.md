# PRAMAAN — Frontend

## Housekeeping — delete two dead files first

`src/components/ui.tsx` and `src/components/ui/` are leftover from the
first MVP pass, superseded by `src/components/kit/`. My tooling couldn't
delete them once written — delete both manually before running; nothing
imports them anymore so the app works either way, but they're dead weight.

## Round 3 — brand identity + Decision Intelligence Dashboard

Verified with a real `npm install && tsc --noEmit && vite build` (clean,
zero errors) plus a bundle-size check.

- **Brand:** only had a flattened brand-board screenshot, not exported
  vector files -- rebuilt the mark as inline SVG (`src/components/kit/Logo.tsx`,
  also used for `public/favicon.svg`) matching the shape/gradient/sparkle
  shown. Swap the `<path>` data in that one file if real SVG/PNG/ICO assets
  become available later. Palette hex codes converted to HSL and stored as
  tokens in `src/index.css` (kept the "no hardcoded colors" rule).
- **Removed glassmorphism/glow effects** added in the previous pass (header
  backdrop-blur, glowing background orbs on Login) -- the brief explicitly
  ruled these out ("no glassmorphism, no neon, enterprise products feel
  smooth not flashy").
- **Header:** 12-hour clock with AM/PM + date, theme toggle switch, and a
  real Profile/Settings/Logout dropdown menu. Profile and Settings are
  intentionally **Frontend Placeholder** -- Profile has a real endpoint
  (`GET /auth/profile`) but no update endpoint yet, and there's no
  Settings endpoint at all, so both currently just say so via a toast
  rather than opening a broken page.
- **AI Credits widget** (sidebar + a Dashboard stat tile): static values
  exactly as specified. **Backend Required Later** for real metering,
  plan/billing endpoints. The Upgrade/Buy Credits buttons are wired to a
  toast saying billing isn't live yet, instead of doing nothing silently.
- **Dashboard rebuilt as a "Decision Intelligence Dashboard"** per the
  brief, but with one deliberate deviation from the reference: the
  reference showed a "Pipeline Value ₹48.7 Cr" stat and a "68% of
  government AI & IT tenders" insight. Neither is buildable honestly right
  now -- there's no tender-value field anywhere in the real API contract,
  and the 68%-style number is a market-wide claim with no data behind it.
  Instead: Active Evaluations, GO Recommendations, Success Rate, Critical
  Gaps, and AI Credits are all computed from real mission/evaluation data
  (fetched and aggregated client-side across every completed mission, not
  just the latest one). "AI Insights" surfaces the single most frequently
  recurring unresolved requirement across your evaluation history -- a
  real frequency count, not a fabricated recommendation. "Upcoming
  Deadlines" and "Latest Reports" from the reference were left out
  entirely: both need list endpoints that don't exist yet (**Backend
  Required Later**: `GET /tenders`, and a stored-reports endpoint).
- **Mission Pipeline funnel** uses the real `MissionStatus` enum values
  (created/running/awaiting_approval/completed/archived) as its stages,
  not the reference's invented stage names -- the backend doesn't track
  anything more granular than that.
- **"Missions" renamed to "Tender Workspace"** (your choice from the 4
  options). Only the nav label and page title changed — the route path
  (`/missions`) and all backend calls are untouched. Each mission now
  shows a real progress stepper driven by its actual status field instead
  of a flat list row.
- **PDF report**, replacing the old .txt export: `src/lib/pdfReport.ts`
  generates a real PDF client-side with jsPDF (header band, executive
  summary, confidence breakdown, risk assessment, full compliance matrix,
  footer with page numbers) — no backend endpoint needed. The import is
  lazy-loaded (dynamic `import()`) only when the button is clicked, so the
  ~360KB jsPDF dependency chain doesn't bloat every other page's load.
- **Decision Engine hero** got a left accent stripe (colored by GO/NO-GO/
  review), a bigger confidence ring, and an eyebrow label for stronger
  visual hierarchy, per the brief.

## Round 2 — visual QA fixes (previous pass)

Verified this time with a real `npm install && tsc -b && vite build` in
sandbox (finally succeeded) — not just manual review. Zero type errors,
clean build.

- **Login brand panel contrast bug, fixed at the root.** The panel used
  `bg-accent`/`text-accent-foreground` (tokens that intentionally flip
  between light/dark mode) as a container, but child text was hardcoded
  `text-white/*`. In dark mode `--accent` flips to a *light* color while
  the hardcoded text stayed white → unreadable. Fix: added `--brand` /
  `--brand-foreground` tokens that are identical in both `:root` and
  `.dark` (see `src/index.css`) — the brand panel is now always the same
  look regardless of OS theme, the way Stripe/Linear's marketing-side
  auth panel never inverts. Applied to `src/pages/Login.tsx`.
- **Dashboard/Documents/Missions responsiveness.** `Layout.tsx` now has a
  proper mobile drawer (hamburger + overlay) instead of an always-on
  240px sidebar that would've broken on phones. Dashboard's two content
  cards are now `lg:grid-cols-2` (side by side) instead of stacked full
  width, and empty states have a `compact` variant so an empty card
  doesn't force extra scrolling.
- **Live clock**, solved once, globally: `src/components/kit/Clock.tsx`
  (`LiveClock`, ticks every second off `Date()`, no backend needed) is in
  the topbar in `Layout.tsx` (visible on every page) and again as a
  "synced as of" stamp on the Documents page specifically.
- **Document delete — deliberately not added.** Checked the real API
  contract: there's no `DELETE /api/v1/documents/{id}` (or anything
  similar) anywhere in the OpenAPI spec. Adding a delete button would mean
  either faking it client-side (misleading) or building a backend endpoint
  that wasn't asked for. Flagging it here as a real gap if delete is
  wanted later.
- **Mission "awaiting approval" — no approve/reject action, on purpose.**
  Same reasoning: there's no endpoint in the contract to change a
  mission's status. The status is now shown with a short explanatory note
  instead of looking like a broken/missing button.
- **Decision Engine result page — restructured, not just restyled.** This
  was the biggest complaint: 40 compliance-matrix rows in one flat list,
  most of them leading with generic reasoning text or a full raw record
  dump instead of the actual requirement, and a separate "Gap Analysis"
  section repeating most of the same 26 items again. Fixed by:
  - Joining `compliance_matrix` entries to `gap_analysis` entries by
    `requirement_id` so every row's heading is the actual requirement
    description (gap_analysis has it for all 26 non-"met" rows; the
    remaining 14 "met" rows use the already-well-written `notes` field
    instead, since gap_analysis never includes fully-met requirements).
  - Raw `supporting_evidence` (the full matched record) is now a
    collapsed `<details>` toggle per row instead of always-visible text.
  - Rows are grouped into collapsible sections by status (Not Met /
    Review Required / Conditional / Met), attention-needed groups expanded
    by default, "Met" collapsed to just a count.
  - A new "What's Blocking This Bid" panel surfaces only mandatory +
    not-met items right after the hero card — the one thing a business
    stakeholder actually needs before reading the detailed matrix.
  - The standalone Gap Analysis section was removed entirely since its
    content is now folded into the above two places — no more duplicate
    data in two different formats on one page.

## Design system, in brief

- **Palette:** deep indigo primary (not Tailwind's default blue — that
  reads as "default template") + a warm neutral scale, defined once as
  HSL CSS variables in `src/index.css`, consumed everywhere via Tailwind
  tokens (`bg-primary`, `text-muted-foreground`, etc). Dark mode is the
  same token set with different values, toggled via a `.dark` class —
  no page ever hardcodes a color.
- **Component library:** `src/components/kit/` — Button, Card (+Header/Body/Stat
  variants), Badge (single semantic status→tone mapping used everywhere,
  so "met"/"go"/"low risk" are always green, "not_met"/"no_go"/"critical"
  always red, consistently across every page), ConfidenceBar/Ring,
  Dropzone (drag & drop), Skeleton loaders, EmptyState, AIProcessing
  (staged loading state for real LLM calls), SearchInput/FilterChip.
- **Typography:** Inter, tabular-nums on all numeric/confidence values so
  columns of numbers align.
- **Motion:** subtle only — fade-in, shimmer on skeletons, a soft pulse
  ring on the active dropzone. Nothing gratuitous.

## Original MVP scope (still true)

Vite + React + TypeScript + Tailwind. No Redux, no extra state library —
`AuthContext` + local component state only, per the MVP brief.

Built directly against the real `/openapi.json` from the running backend
(fetched and confirmed, not guessed) — see `src/api/types.ts` and
`src/api/endpoints.ts`.

## 1. Backend requirement — CORS (do this first)

Your backend currently has no CORS middleware. A browser will block every
request from this frontend (`localhost:5173`) to the backend
(`localhost:8000`) until this is added. In `app/main.py`, near where the
`FastAPI()` app is created, add:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This is the one backend change required to make the frontend work at all.
Everything else in the MVP brief ("backend frozen except for bugs") still
holds — this isn't a feature, it's infrastructure the frontend can't
function without.

## 2. Setup

```
npm install
cp .env.example .env
npm run dev
```

Opens at `http://localhost:5173`. Make sure the backend is running at
`http://127.0.0.1:8000` (or update `VITE_API_BASE_URL` in `.env`).

## 3. Flow implemented

Login/Register → Dashboard → Documents (upload) → Capabilities (build +
view) → New Tender (upload) → Tender Detail (run analyzer, view
requirements) → Decision Engine (run evaluation, view recommendation +
compliance matrix + gap analysis — the hero page).

## 4. Assumptions made against the real contract — verify these on first run

- **`POST /api/v1/tenders/upload` response shape.** The OpenAPI spec marks
  this endpoint's response as a loosely-typed object (`additionalProperties:
  true`), not a named schema. The frontend assumes it returns at least
  `id` (the tender id) and `mission_id`, matching the shape of `TenderRead`
  used elsewhere. If the real response doesn't include these fields, the
  redirect after upload will show an explicit error rather than fail
  silently (see `TenderUpload.tsx`) — check that error message first if
  upload seems to "not go anywhere."
- **`POST /api/v1/capabilities/build` response** is also loosely typed
  (`additionalProperties: true`) — the frontend doesn't depend on its
  response shape at all, it just re-fetches `GET /api/v1/capabilities`
  afterward, which *is* strictly typed. This sidesteps the ambiguity
  entirely rather than guessing.
- **Document types** on the upload form (`certification`,
  `employee_resume`, `project_record`, `equipment_record`,
  `financial_record`, `other`) are a guess — the OpenAPI schema only says
  `document_type` is a plain string, no enum. If the backend expects
  different literal values, update the `DOCUMENT_TYPES` array in
  `Documents.tsx`.

## 5. What's deliberately NOT here (per the MVP brief)

No admin panel, user management, notifications, charts/analytics
dashboard, settings, billing, monitoring, audit logs, dark mode, or
animations beyond a basic loading spinner. Those are later phases.

## 6. If frontend integration surfaces a real backend issue

Per the brief: report it, don't silently redesign the backend. Two things
already flagged as worth knowing before heavy use:

- `POST /api/v1/analysis/run` and `POST /api/v1/evaluation/run` are both
  synchronous, blocking HTTP calls — Decision Engine in particular calls
  Gemini once per requirement in a loop. A large tender (dozens of
  requirements) could mean a multi-minute blocking request with no
  progress feedback beyond the button's "Running…" state. Fine for MVP
  demo-sized documents; worth a real look before testing very large
  tenders through this UI.
- The `/api/v1/tenders/upload` and `/api/v1/capabilities/build` response
  types are looser than the rest of the API (see above) — worth tightening
  to named schemas at some point so the frontend isn't relying on
  duck-typing.
