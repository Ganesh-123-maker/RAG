# Phase F — Frontend & UX: Report

Branch: `phase-f-frontend` (from `phase-e-hardening`, stacks on PR #5).
No changes were made to `main` or to earlier phase branches; no
history was rewritten, no force-push was used, and no secrets,
`.env`, `uploads/`, `node_modules/`, or build output were committed.
Backend behaviour is unchanged except for one additive endpoint
(the rename PATCH, below). Phase A–E behaviour is preserved: one
LangGraph path, threshold + MMR, chunk-id citations, graded graph,
real eval runner, httpOnly auth, rate limits, and observability
are untouched.

## What changed

### F1 — Auth + API client
- `frontend/lib/api.ts` is now a SINGLE shared axios instance.
  Previously `authApi()` created a brand-new instance per call, so
  no interceptor could ever be shared. `authApi` remains as an
  alias for the same instance so existing imports keep working.
- A response interceptor redirects to `/login` on 401 (except on
  `/login` itself, where a redirect would loop). The redirect
  decision is a pure function (`shouldRedirectOnUnauthorized`,
  unit-tested); the fetch-based stream path handles 401 explicitly
  in `ChatPanel` because axios interceptors cannot catch `fetch`.
- Safe error messages: `getApiErrorMessage()` prefers the backend's
  `detail` string and never surfaces a stack trace or a nested
  object; login/register/dashboard/chat all use it now instead of
  ad-hoc `error.response?.data?.detail || "…failed"`.
- Auth drift is fixed by NOT reintroducing JS tokens: verified by
  grep that no app code sets or reads a token cookie (`js-cookie`
  usage was already gone after Phase E; the dependency itself is
  now removed from `package.json`). Cookie lifetime remains
  backend-controlled (60-minute httpOnly cookie, Phase E).
  Register auto-login already posted JSON after Phase E; verified
  in code and now covered end-to-end by the Playwright spec.
- Loading skeletons + error states: the dashboard shows skeleton
  rows while loading, and a document/conversation list failure now
  shows an error banner with a Retry button instead of silently
  rendering an empty list.

### F2 — Streaming UX
- Stop/cancel: an AbortController + `reader.cancel()` on the Stop
  button and on panel unmount. The backend already persisted the
  partial assistant message in the stream generator's
  `finally`-block (`backend/app/routers/chat.py`), verified in code;
  the frontend now also KEEPS the partial text instead of deleting
  the assistant placeholder on abort/error (the old behaviour).
- Retry last message (shown after a failed stream) and Regenerate
  (re-asks the last user question). Regenerate is honestly a fresh
  re-ask, not an in-place replacement: the backend has no
  replace-message endpoint, so it appears as a new turn. This is
  documented here rather than hidden.
- Copy answer button per assistant message (clipboard with a
  failure toast).
- Markdown + code rendering with sanitisation: `rehype-sanitize`
  added to the ReactMarkdown pipeline. No `rehype-raw` and no raw
  HTML rendering anywhere (verified by grep; a test asserts an
  `<img onerror>` in model output is not rendered as an element).
- Citation chips open a source panel (`components/CitationPanel.tsx`,
  a labelled dialog) showing document name, chunk index, chunk id,
  page, section, score, and snippet — using the Phase B/C citation
  fields. Missing page/section render as "Not recorded".
- Conversation list: rename (inline edit, Enter to save, Escape to
  cancel) + delete + "load more" (15 at a time). Load-more was
  chosen over server pagination: the backend list endpoint returns
  all conversations and changing it would have been a gratuitous
  backend change for a sidebar that rarely exceeds a few dozen
  rows; the trade-off is recorded here.
- Document list: status badges now include `queued`, a progress bar
  (from `ingestion_progress`) for non-terminal documents, and the
  backend `error_message` rendered under failed documents.
  Polling: the dashboard refetches documents every 2.5s ONLY while
  any document is `queued`/`processing`, and stops as soon as all
  are terminal.
- Drag-and-drop upload with client-side validation
  (`lib/validation.ts`, mirroring the backend: PDF/DOCX/TXT/MD,
  50 MB, non-empty) plus dropzone `maxSize` and a rejection toast.
  The backend still enforces both limits; this only fails fast
  with a clear message before bytes are uploaded.

### F2 backend addition (justified, minimal)
- `PATCH /api/v1/chat/conversations/{id}` with
  `ConversationUpdate` (title stripped, 1–200 chars, empty → 422),
  `ConversationRepository.update_title_for_owner()` (owner-scoped;
  another user's conversation is a 404, indistinguishable from a
  missing one). No other backend behaviour changed.

### F3 — Responsive / mobile / accessibility / theme
- Mobile sidebar: the fixed `w-72` sidebar is now desktop-only
  (`hidden md:flex`); on mobile a hamburger button opens it as an
  overlay dialog with a backdrop click and a close button.
- Keyboard: Enter sends, Shift+Enter newline (pre-existing,
  verified and kept), Escape cancels a rename, focus returns to
  the chat input after stopping generation.
- ARIA: labels on send/stop/copy/regenerate/rename/delete/sidebar
  toggle, `aria-expanded` on the citation toggle, `role="log"` +
  `aria-live="polite"` on the message list, `role="progressbar"`
  with values on ingestion progress, dialog roles on the citation
  panel and mobile sidebar.
- Contrast (measured, not guessed, against the `#0f0f1a`
  background): slate-100 17.4:1, slate-200 15.4:1, slate-300
  12.8:1, slate-400 7.4:1, brand-300 9.6:1 — all pass WCAG AA for
  normal text. The exception is slate-500 secondary text at
  4.0:1, below AA's 4.5:1 for normal text. This was NOT fixed by
  a sweeping class change in this phase (it would touch every
  secondary label); it is recorded as a known limitation for a
  token-level pass, not hidden.
- Empty states: kept and improved (no documents / no
  conversations messages, plus the new error states above).
- **Dark/light theme toggle: SKIPPED deliberately.** The theme is
  hardcoded dark throughout `globals.css` (dark surfaces, dark
  gradients, dark scrollbars) and every component uses dark slate
  classes; Tailwind's `darkMode: "class"` alone changes nothing
  without a full light palette. A toggle that flips a class but
  leaves dark surfaces would be a broken feature, worse than
  dark-only. The toggle belongs with a real light-palette pass,
  not bolted on here.

### F3-bonus — a real bug found by the E2E spec (CSP breaks hydration)
- Phase E's CSP (`default-src 'self'`, no script-src) blocked
  Next.js's own inline scripts, so hydration never completed in
  dev OR production: forms submitted natively (the register form
  landed on `/register?` with no API call at all). This means the
  app as shipped after Phase E could not actually sign users up
  in a browser — the build passing had hidden it, because no
  browser test existed.
- Fix (`frontend/next.config.js`): `script-src 'self'
  'unsafe-inline'` (inline scripts are required for Next.js
  hydration without nonce plumbing; `'unsafe-eval'` is still NOT
  allowed) and explicit Google Fonts allowances for the stylesheet
  `globals.css` already imports (previously silently falling back
  to system fonts). A nonce-based CSP is the Phase G follow-up;
  the comment in `next.config.js` says so, so this widening is
  not silent.

### F4 — Frontend tests
- Vitest + React Testing Library + jsdom added (`vitest.config.ts`,
  `vitest.setup.ts`, `npm test` script). Notes from getting it to
  run: Vitest 5 needed `vite` and `@vitejs/plugin-react` as explicit
  devDeps (Next's `jsx: preserve` tsconfig otherwise fails to
  parse `.tsx` tests), and `@testing-library/dom` as an explicit
  peer of jest-dom v7.
- 17 Vitest tests, all passing (see Tests): SSE parser
  (split chunks, partial-line flush, malformed lines, done/error
  semantics), API error/401 helpers, upload validation, citation
  panel rendering, ChatPanel streaming (split tokens, status,
  citations → panel, stop-keeps-partial, 401 → retry, HTML
  sanitisation), dashboard (progress + error_message, polling +
  retry, rename via PATCH).
- One test bug found and fixed during development, honestly
  recorded: the dashboard test's mocked `useRouter` returned a
  fresh object per render, which changed `fetchData`'s identity
  every render and re-ran its effect forever (~9,700 renders in
  15s). In production Next's router is stable, so this was a
  test-mock artifact, not a production bug; the mock now returns
  a stable router object, and the comment in the test says so.
- Playwright E2E (`frontend/e2e/journey.spec.ts`,
  `playwright.config.ts`, `npm run test:e2e`): signup → upload →
  ask → cited answer → open source panel. It runs in two modes
  and NEVER needs a real OpenAI key: `E2E_MOCK_API=1` (default)
  intercepts every API call, so only the frontend server is
  needed; `E2E_MOCK_API=0` exercises a real backend from the
  docker stack for signup/upload while still intercepting only
  the chat stream (the LLM). How to run it is documented in the
  spec header and below.

## How to run the E2E spec
```bash
cd frontend
npm run build && npm run start     # production server on :3000
npx playwright install chromium    # once, if browsers are missing
npx playwright test                # mock-API mode, no key needed
# Against a real backend (docker stack up, no OpenAI key needed):
E2E_MOCK_API=0 npx playwright test
```

## Tests
- Frontend Vitest: **17 passed, 0 failed** (6 files).
- `npx tsc --noEmit`: clean. `npm run lint`: clean (no warnings).
- `npm run build`: succeeds (7 pages; dashboard 71.3 kB / 183 kB
  first load). `.next/` removed after the build, not committed.
- Playwright E2E: **1 passed** against the production build
  (`npm run start`) in mock-API mode. The failing runs were fixed,
  not ignored: (1) the CSP hydration bug above, (2) an
  ambiguous-text assertion in the spec (the snippet appears in
  the answer, the chip, and the panel — now scoped to the dialog).
  No E2E pass is claimed for the docker-stack mode
  (`E2E_MOCK_API=0`): it was not run here because Docker is not
  available in this sandbox (see below); Phase G's CI job is the
  place that runs it against the stack.
- Backend pytest (proxy vars cleared, CI-equivalent env):
  **122 passed** (117 prior + 5 new rename tests in
  `backend/tests/test_phase_f.py`: success with title trimming,
  empty-title 422, other-user 404, missing-conversation 404,
  repository owner-scoping). No existing test was weakened.
- Docker: NOT run here — `docker` is not installed in this
  sandbox, same caveat as Phases A–E. `docker compose build` and
  the stack smoke test must be verified on a Docker machine
  before merging (Phase G CI will cover this).

## Known limitations (do not over-claim)
- Regenerate is a fresh re-ask (new turn), not an in-place
  replacement — the backend has no replace-message endpoint.
- Conversation "pagination" is client-side load-more; the backend
  list endpoint is unchanged and returns all conversations.
- slate-500 secondary text is 4.0:1, below WCAG AA for normal
  text (see F3 above).
- The theme is dark-only; the light-theme toggle was skipped
  deliberately (see F3 above).
- CSP now allows `'unsafe-inline'` scripts for Next.js hydration;
  a nonce-based CSP is a Phase G follow-up.
- E2E docker-stack mode (`E2E_MOCK_API=0`) and `docker compose
  build` were not run in this sandbox (no Docker); both are
  Phase G CI items, not claimed passes.
- `zustand` remains in `package.json` (unused by any component);
  removing it was out of scope for this phase's diff and is a
  trivial Phase G cleanup.
