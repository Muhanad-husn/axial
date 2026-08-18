# Slice 02: the essay is the answer on screen

- **Feature:** 784-ask-ends-in-an-essay
- **Slice slug:** essay-is-the-answer
- **Branch:** feat/784-ask-ends-in-an-essay/02-essay-is-the-answer
- **Project directory:** `web`
- **Status:** ✅ done
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

An analyst who asks a question in the web client reads an argued essay, and
reaches the claim list behind the same disclosure that already holds the
metrics panel.

## INVEST check

- **Independent:** web only. The API field it reads landed in slice 01.
- **Valuable:** this is the issue's headline. Until it lands, the essay exists
  and nobody sees it.
- **Small:** one new component, one changed component, one dependency.
- **Testable:** a Playwright run against the existing mock service, plus
  component tests under vitest.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the mock service returns a finished ask whose paper payload carries an
      essay
When  an analyst submits a question in the web client and the run settles
Then  the answer area shows the essay's thesis and its section headings as
      prose, with no claim rail visible
And   opening the same disclosure that reveals the metrics panel reveals the
      claim list, rendered exactly as it is today
And   an ask whose payload carries no essay still shows the claim list, with
      a plain line saying no essay was drafted
```

- **Boundary / endpoint:** the web page at `/`, driven through the browser
- **e2e test type:** Playwright (screenshots + video evidence)
- **e2e test file (planned):** `web/e2e/essay.spec.ts`

## Files (parallel-safety declaration)

```aeo-independence
slice: 02-essay-is-the-answer
edits: web/src/components/Paper.tsx
edits: web/src/lib/api.ts
edits: web/src/app/page.tsx
edits: web/src/app/globals.css
edits: web/package.json
edits: web/package-lock.json
edits: web/e2e/mock-service.mjs
edits: web/vitest.config.mts
creates: web/src/components/Essay.tsx
creates: web/src/components/Essay.test.tsx
creates: web/src/components/Paper.test.tsx
creates: web/e2e/essay.spec.ts
depends-on: 01-essay-from-the-ask
```

`web/vitest.config.mts` and `web/src/components/Paper.test.tsx` were added to
this block while building, not planned into it. The config's `include` widens
from `src/**/*.test.ts` to `src/**/*.test.{ts,tsx}` so the new component tests
run at all; `Paper.test.tsx` holds the four `Paper`-level behaviours the inner
loop below calls for and had nowhere else to live. Neither is touched by slice
03, so the two stayed independent. `web/src/app/globals.css` is declared above
and was **not** edited: Tailwind utilities covered the essay and it introduced
no new colour.

## Design decisions this slice makes

1. **Render the markdown with `react-markdown`, do not hand-roll a parser.**
   The essay is a markdown string with headings, paragraphs and blockquotes.
   Checked first, per the developer principles: nothing in `web/` renders
   markdown today, no installed component does it, and the alternative — a
   second server-side render that returns structured sections — means
   maintaining two renders of one artifact. One dependency (plus `remark-gfm`
   only if the drafter's prose actually needs a table or a strikethrough;
   confirm against a real essay before adding it).
2. **The claim list moves, it does not change.** `Paper.tsx` keeps rendering
   `record.claims` exactly as it does now, including its rail, markers and
   citation lines — it moves inside the disclosure. Its own docstring's promise
   ("nothing is re-sorted, re-grouped or computed") stays true.
3. **Refusal keeps its own path.** `Paper.tsx:51` already branches on
   `record.interrogation.disposition`; a refusal renders as a refusal, above
   any essay question, and no essay is expected or announced as missing.
4. **No essay is stated plainly, never silently.** A missing essay means the
   drafting failed or was skipped. The client says which of the two it can tell
   and shows the claim list — it never presents the claim list as though it
   were the intended answer.
5. **Evidence colour rules are unchanged.** Three markers, nothing else
   coloured (#770). The essay's own citation parentheticals come from the
   server's reader render; the client adds no new colour.

## Inner loop — initial unit test list

- [x] `Essay` renders a thesis and every section heading from a markdown
      string, in order.
- [x] `Essay` renders a blockquote as quoted book text, visually distinct from
      the tool's own prose.
- [x] `Paper` shows the essay and hides the claim list when `essay` is present.
- [x] `Paper` shows the claim list plus a stated absence when `essay` is
      missing.
- [x] `Paper` renders a refusal unchanged whether or not `essay` is present.
- [x] The claim list inside the disclosure renders the same DOM it renders
      today (a snapshot pinning the move as a move).

## Out of scope for this slice (deferred)

- Streaming sections as they draft — slice 03.
- Any change to the metrics panel's own contents.
- Print/typographic styling beyond what the existing type scale gives.
- The export button's contents (server-side, slice 01).

## Definition of done

- [x] Acceptance test written, seen to fail for the right reason, now GREEN.
- [x] Screenshots of both states (essay present, essay absent) collected as
      PR evidence, plus a recording of one run.
- [x] `npm run lint`, `npm run typecheck`, `npm run test` green in `web/`.
- [x] **The rendered picture is looked at before the taste calls are
      settled** — the essay's measure, heading rhythm and quote treatment
      judged from a render, not from the markup (#770's rule).
- [x] Playwright orphan node processes killed before any worktree cleanup.
- [ ] Slice's tests run in CI.
- [ ] Evidence collected and PR opened via `/aeo:safe-pr`.

## Status / progress log

- 2026-08-17 planned.
- **2026-08-18 built.** Outer loop: `web/e2e/essay.spec.ts`, watched red with
  `getByTestId('essay')`/`getByTestId('no-essay')` both "element(s) not
  found" against the real app and the mock service, before any production
  line. Inner loop, outside-in: `Essay.tsx` (`react-markdown`, no
  `remark-gfm` -- confirmed against every real essay in `data/papers/*.md`,
  none uses a table or a blockquote) driven by `Essay.test.tsx`; `Paper.tsx`
  driven by `Paper.test.tsx`, the first two component-level tests in `web/`
  (`@testing-library/react` + `jsdom` added, opted in per-file with
  `// @vitest-environment jsdom` so every pre-existing `.test.ts` stays on
  `node`, unchanged).
- **`web/e2e/paper.spec.ts` was not edited, on purpose (not in the plan's own
  file list) and still passes unedited.** Its two cases (`Damascus`,
  `Aleppo`) stay essay-less by construction -- the mock's `"Beirut"` case
  carries the new fixture -- so the claim list they assert against renders
  exactly as it did before this slice, unwrapped, and `paper.spec.ts` keeps
  proving the marker/citation-mode rendering `essay.spec.ts` does not
  re-test.
- **"The same disclosure that reveals the metrics panel" read as the same
  UI mechanism (a native `<details>`), not a shared instance.** Sharing one
  `<details>` with `MetricsPanel` would open both together, contradicting
  `paper.spec.ts`'s own existing test that opens metrics without opening
  claims. The claims disclosure is its own element, styled identically.
- **The disclosure only exists when there is something to disclose.** No
  essay means the claim list renders exactly as `paper.spec.ts` pins it
  today -- unwrapped, visible with no click -- behind one plain line. An
  essay present is the only state that gets a closed `<details>`.
- Screenshots (`essay-present.png`, `essay-claims-opened.png`,
  `essay-absent.png`) and two run recordings collected under
  `D:/axial/data/logs/2026-08-18-784-slice-02/` (gitignored, outside this
  repo's tracked tree) -- the taste call was made from these before this box
  was ticked.
- No orphan node process matched the worktree slug after the Playwright
  runs; nothing to kill before cleanup.
