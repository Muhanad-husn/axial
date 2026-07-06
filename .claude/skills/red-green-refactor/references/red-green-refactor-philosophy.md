# Red-Green-Refactor: Philosophy & Discipline

> The authoritative reference for an enterprise-grade, AI-driven automated TDD harness. Every rule below is written to be executed literally by an autonomous coding agent. Where a rule is load-bearing, the originating source is cited.

---

## 1. The Core Thesis of TDD — and Why It Matters for Enterprise Software

Test-Driven Development is not a testing technique. It is a **design discipline** that happens to leave a regression suite behind as a by-product. Its goal, in Kent Beck's framing (attributed to Ron Jeffries), is **"clean code that works"** — and the method splits that goal in two and solves the halves *in order*:

> "First we'll solve the 'that works' part of the problem. Then we'll solve the 'clean code' part." — Kent Beck, *TDD by Example*

The discipline is driven by a tight, repeating micro-cycle — **Think → Red → Green → Refactor** — executed in tiny increments, "only a few lines of code at a time" (James Shore). Martin Fowler defines TDD as "a technique for building software that guides software development by writing tests," and identifies its **two simultaneous benefits**:

1. It produces **self-testing code**: "You have self-testing code when you can run a series of automated tests against the code base and be confident that, should the tests pass, your code is free of any substantial defects." (Fowler)
2. It **forces attention onto the interface before the implementation**: "Thinking about the test first forces us to think about the interface to the code first... a key element of good design that many programmers struggle with." (Fowler)

**Why this matters at enterprise scale:**

- **The expensive part of programming is finding mistakes, not fixing them** (Shore). By keeping each change to a handful of lines between known-good states, a defect can only hide in those few lines, so the next red bar or failed compile pinpoints it in seconds. This collapses the most costly activity in software to near-zero.
- **Confidence to change the system.** "The biggest benefit isn't about merely avoiding production bugs, it's about the confidence that you get to make changes to the system." (Fowler) For an autonomous agent operating on a large codebase, the green suite is the *only* trustworthy signal that a change is safe.
- **Fear management.** "Tests are the Programmer's Stone, transmuting fear into boredom." (Beck) The agent should treat unexpected red as a signal to slow down, not push harder: "The more stress I feel, the more I run the tests."
- **Tests are a means, not an end.** "In TDD, the tests are means to an end — the end being code in which we have great confidence." (Beck) The harness optimizes for *confidence and design feedback*, not for coverage as a vanity metric.

---

## 2. The Red-Green-Refactor Cycle — Step by Step, With Discipline

The canonical cycle has a **vital initial step** that precedes the loop:

> "Although these three steps, often summarized as Red - Green - Refactor, are the heart of the process, there's also a vital initial step where we write out a list of test cases first." — Fowler

GOOS extends the inner cycle to **four explicit steps**, adding a "make the failure clear" check between Red and Green:

> "Write a failing test → Make the diagnostics clear → Make the test pass → Refactor." — *Growing Object-Oriented Software, Guided by Tests*

### Phase 0 — THINK (choose the next test)

This is the hardest and most important step. "Figure out what test will best move your code towards completion. (Take as much time as you need. This is the hardest step for beginners.)" (Shore). "Sequencing the tests properly is a skill, we want to pick tests that drive us quickly to the salient points in the design." (Fowler)

- **MAY:** Maintain and extend a living test list; add tests to it as they occur to you.
- **MAY:** Spend disproportionate time here — design thinking lives in slice selection.
- **MUST:** Pick exactly **one** test — the smallest behavior that moves the code toward completion.
- **MUST NOT:** Begin writing production code before a failing test justifies it.

### Phase 1 — RED (write one small failing test)

> "Write a little test that doesn't work, and perhaps doesn't even compile at first." — Beck

- **MUST:** Write a single, small failing test (~5 lines) for the next minimum testable behavior.
- **MUST:** **Run it and watch it fail.** "Run the tests and watch the new test fail: the test bar should turn red." (Shore) A test never seen to fail may be asserting nothing.
- **MUST:** Confirm it **fails for the right reason** with a readable diagnostic before writing any production code (GOOS step 2). "Never skip the red step. If you cannot articulate why a test fails, you do not yet understand the requirement." (Searls)
- **MAY (London school):** Make interface/protocol design decisions *here* by mocking collaborators — "design decisions happen in the RED phase, while we write the test." (Dan the Dev)
- **MUST NOT:** Write more than one logical behavior's worth of test.
- **MUST NOT:** Skip running the test, or proceed on a test that fails for the wrong reason (e.g., a typo, missing import, or compile error you intended to be a real assertion failure).

### Phase 2 — GREEN (make it pass, fast)

> "Make the test work quickly, committing whatever sins necessary in process." — Beck

- **MUST:** Write the **minimal** production code that makes the failing test pass — and nothing more.
- **MAY:** Commit any "sin" to get to green — **hard-code a constant, fake the answer**, write ugly code. "Don't worry about design purity or conceptual elegance. Sometimes you can just hardcode the answer. This is okay because you'll be refactoring in a moment." (Shore)
- **MUST:** Run the full suite and confirm the bar is **green** before proceeding.
- **MUST NOT:** Implement variations, edge cases, or behaviors **not yet demanded by a test** (gold-plating). Code is written "only in response to making a test pass." (Fowler)
- **MUST NOT:** Pursue design purity or elegance here — that is deferred to Refactor.

### Phase 3 — REFACTOR (clean up, only on green)

> "Eliminate all of the duplication created in merely getting the test to work." — Beck

- **PRECONDITION:** All tests are green. **Never refactor on a red bar.**
- **MUST:** Improve structure only — remove duplication, clarify names, extract collaborators — **without changing behavior.**
- **MUST:** Re-run the tests after **each** small refactoring. "After each little refactoring, run the tests and make sure they still pass." (Shore)
- **MUST:** If a refactor breaks a test, **revert the refactor — do not fix forward.** (Searls)
- **MUST NOT:** Add new functionality during refactoring. New behavior belongs in a new Red-Green cycle.
- **NOTE:** This step is non-optional. "The most common way that I hear to screw up TDD is neglecting the third step." (Fowler) Skipping it yields "a messy aggregation of code fragments."

### Phase 4 — REPEAT

Return to THINK and pick the next test. The loop runs dozens of times an hour — "20-40 cycles in an hour is not unreasonable" (Shore): several fast slices, then a slower heavier-refactor slice, then fast again.

---

## 3. Kent Beck's Two Rules and the Small-Step Patterns

### The two rules that generate the entire rhythm

1. **"Write new code only if an automated test has failed."**
2. **"Eliminate duplication."**

Everything else — the whole red/green/refactor cadence and the emergence of good design — falls out of obeying these two rules relentlessly.

### The escalating-uncertainty ladder (how big a step to take)

Match step size to confidence. Beck's ordering, from most confident to least:

| Pattern | When to use it | What you do |
|---|---|---|
| **Obvious Implementation** | "If you know what to type, and you can do it quickly, then do it." | Type the real implementation directly. |
| **Fake It** | You don't yet know the real code, or you want a trivial first slice. | "Return a constant and gradually replace constants with variables until you have the real code." |
| **Triangulation** | "I only use Triangulation when I'm really, really unsure about the correct abstraction." | Force the abstraction with a **second example**: "Abstract only when you have two or more examples. When the second example demands a more general solution, then and only then do we generalize." |

**Downshifting rule (critical for an autonomous agent):** "As soon as I get an unexpected red bar, I back up, shift to faking implementations" and take smaller steps. "Be prepared to downshift if your brain starts writing checks your fingers can't cash." When confident and everything is smooth, string Obvious Implementations together; the moment reality surprises you, shrink the slice.

**Over-generalization is an antipattern:** never abstract from a single example. One example → Fake It (constant). Two examples → Triangulate to the real abstraction.

---

## 4. Thin Vertical Slicing, Minimum Testable Behavior, and the Walking Skeleton

### Slice vertically, never horizontally

> A vertical slice is "a work item that delivers a valuable change in system behavior such that you'll probably have to touch multiple architectural layers to implement the change." — Humanizing Work

Build **feature-by-feature, end-to-end**, not layer-by-layer:

> Instead of "Implement the database layer for A, B and C" then logic then UI, you "Implement A from end to end" then B and C. — John Sonmez

Horizontal slicing (DB layer, then logic, then UI) produces no independently valuable or testable increment and defers integration dangerously to the end. **This is forbidden.**

### Minimum testable behavior

Decompose every feature down to **the smallest observable change in system behavior that delivers value and can be verified** — the single tiny goal for one cycle (e.g., "handle null input," "implement core logic for rule Z"). The core rhythm of vertical slicing is: *test fails → minimum code passes → next round.*

### The INVEST quality bar for a slice

**I**ndependent · **N**egotiable · **V**aluable · **E**stimable · **S**mall · **T**estable. "If a story does not have discernable value it should not be done. Period." A slice should be deliverable within an iteration; for this harness, target a slice completable in **hours, not days — ideally under a day**, so it is one red-green-refactor pass and one PR.

### Nine concrete splitting patterns (Humanizing Work)

1. **Workflow Steps** — build the simple end-to-end case first, then add middle steps/special cases.
2. **Operations / CRUD** — split "manage X" into Create / Read / Update / Delete.
3. **Business Rule Variations.**
4. **Variations in Data** — start with one data variation, add others just-in-time.
5. **Data Entry Methods** — simplest UI first.
6. **Major Effort** — do the part that carries the bulk of the work first.
7. **Simple / Complex** — extract the simplest viable version; defer edge cases to separate slices.
8. **Defer Performance** — split "make it work" from "make it fast / secure / scalable."
9. **Break Out a Spike** — time-boxed investigation to resolve genuine uncertainty.

**Meta-pattern:** identify the core complexity → list all the variations → reduce to **just one** variation for the first slice.

### The Walking Skeleton (the first slice of a new system)

> "A walking skeleton is an implementation of the thinnest possible slice of real functionality that we can automatically build, deploy, and test end-to-end." — GOOS

> "A Walking Skeleton is a tiny implementation of the system that performs a small end-to-end function. It need not use the final architecture, but it should link together the main architectural components." — Alistair Cockburn

Its purpose is to **de-risk architecture and infrastructure first** — CI, deployment scripts, repo/project setup, component wiring, communication mechanisms — *before* piling on features. "The point of the walking skeleton is to help us understand the requirements well enough to propose and validate a broad-brush system structure." (GOOS) It lets you **test-drive the architecture** and evolve it as later slices reveal pressure, rather than committing to big design up front.

---

## 5. Double-Loop / Outside-In TDD — How Unit Tests and E2E/Integration Tests Relate in One Cycle

Double-loop TDD (a.k.a. outside-in, ATDD, London school, as taught in GOOS) structures development as **two nested red-green-refactor loops operating at different timescales.**

```
┌─────────────────────────────────────────────────────────────┐
│  OUTER LOOP  —  acceptance / e2e / integration  (hours–days) │
│  RED: failing acceptance test (feature absent; progress meter)│
│   │                                                          │
│   │   ┌───────────────────────────────────────────────┐     │
│   │   │  INNER LOOP — unit tests (minutes)            │     │
│   │   │  RED → make failure clear → GREEN → REFACTOR  │ ◄─┐ │
│   │   │  (repeat per class, working inward, mocking   │   │ │
│   │   │   not-yet-built collaborators)                │   │ │
│   │   └───────────────────────────────────────────────┘   │ │
│   │            loop until acceptance test CAN pass ────────┘ │
│   ▼                                                          │
│  GREEN: re-run acceptance test → if red, back to inner loop  │
│  REFACTOR: clean up across module/boundary at larger scale   │
└─────────────────────────────────────────────────────────────┘
```

### The three test levels (GOOS, outside-in)

- **ACCEPTANCE** — does the whole system do what the customer wants, end-to-end, **through real external endpoints**? "An integration/acceptance test should exercise the system end-to-end without directly calling its internal code. It should interact with the system only from the outside, through the external endpoints (e.g. calling the web service)." (GOOS) Written in the **user's/domain language** (GIVEN-WHEN-THEN).
- **INTEGRATION** — does our code work with code/infrastructure we **cannot change**?
- **UNIT** — do our objects behave correctly **and have good design**? ARRANGE-ACT-ASSERT, run in milliseconds.

### Exactly how the two loops relate within one cycle

This is the crux of using **both** e2e/integration tests **and** unit tests in a single workflow:

1. **The failing e2e/acceptance test sets the goal and gates the feature** — the *"what / are we done"* signal. "The first thing we do with a new feature is write a failing acceptance test... [it] demonstrates that the system does not yet have the feature we're about to write and tracks our progress towards completion of the feature." (GOOS) It is a **progress meter + regression guard**.
2. **The unit tests build and verify the internals that make it pass** — the *"how / quality"* signal. They drive the design of each class, working **inward from the boundary**, mocking dependencies that don't exist yet.
3. **You literally cannot finish the slice until the e2e test is green, and you never write internal code without a unit test** — so **both suites grow together**. Stemmler: "The outer loop is the acceptance test loop and it catches regressions. The inner loop is the unit test loop and it measures progress."

GOOS' division of labor: acceptance tests "set goals for our software's external (user-facing) behaviors," while unit tests "set goals for our software's internal (sub-system) behaviors."

### Outside-in flow (concrete)

Start at the system boundary (UI widget, web endpoint, CLI flag) named by the acceptance test → design the first class it calls → discover its collaborators → replace them with **mocks** → drop a unit-loop down each collaborator in turn → repeat inward until the acceptance test passes. Mocks make design cheap: "It's very cheap to change mocks and experiment until you get the interface and the protocol just the way you want it." (Bache)

### Which school, when

> "Inside-Out when you know how to build it, and Outside-In when you're working out the pieces." — Stemmler

Use **classic/inside-out (Chicago)** when the design is already known; use **outside-in/London** when you must discover collaborators and interfaces. The London school **asserts on messages/interactions** (Tell, Don't Ask) because the goal is to design the communication between objects.

### Test-pyramid alignment

Many fast **unit** tests at the base; fewer **integration/acceptance** tests above; a thin layer of full **end-to-end** at the top. Outside-in writes the top-of-pyramid test *first* but accumulates mostly base-of-pyramid unit tests. **The Searls warning:** never "write a shitload of unit tests chasing the local maximum of code coverage without any regard for the global maximum of making sure shit actually works." Green units with no passing end-to-end proof is a failure, not progress.

---

## 6. Refactoring Discipline

Refactoring is the dedicated third phase of every cycle and the place where deferred design quality is paid back. The cycle deliberately separates *make it work* (Green) from *make it clean* (Refactor).

- **Refactor only on green.** The passing suite is the safety net that proves behavior is preserved. Never restructure while any test is red.
- **Refactoring changes structure/design, never behavior.** If behavior changes, it isn't refactoring — it's a new Red-Green cycle.
- **Hunt duplication first.** Rule 2 — "Eliminate duplication" — is what drives good design to *emerge*. Target especially the duplication and hard-coding left behind by the quick-and-dirty Green step. Also improve names, extract collaborators, and remove other code smells.
- **Take small steps and re-run after each.** "After each little refactoring, run the tests and make sure they still pass." (Shore) Don't batch many structural changes between test runs.
- **If a refactor breaks a test, revert it — do not fix forward.** (Searls)
- **Refactor in both loops.** Inner-loop refactor after each unit goes green (class-level cleanup); outer-loop refactor after the acceptance test goes green (cross-module/boundary cleanup).
- **Listen to the tests.** "When you find unit tests difficult to write or understand... listen to the feedback." (GOOS) Hard-to-write or brittle tests signal a design smell to refactor away — not pain to tolerate.
- **Stay scoped.** Failing tests "keep us focused on implementing the limited set of features they describe." Refactoring stays scoped to what the tests demand; no gold-plating, no speculative generality.
- **On the test suite itself:** never delete a test if doing so would reduce confidence; keep redundant tests when they communicate different scenarios; delete only the least useful among truly redundant tests. Be aware that mock-heavy inner tests are cheap to change during design but couple tests to structure — some teams delete inner mock tests once real implementations exist, keeping acceptance tests for regression. This is a **known trade-off, not a rule.**

---

## 7. Common Antipatterns — and How an Autonomous Agent Avoids Each

| Antipattern | How the agent avoids it |
|---|---|
| **Writing production code with no failing test** (violates Beck rule 1). | Gate every production edit behind a currently-failing test the agent has just observed fail. |
| **Skipping the red bar / never watching the test fail.** | Always run the new test and assert that it fails for the *intended* reason before writing production code; capture and check the diagnostic. "If you cannot articulate why a test fails, you do not yet understand the requirement." (Searls) |
| **Not making the failure clear** (jumping to green on a wrong-reason failure). | Enforce GOOS step 2: parse the failure message; reject failures caused by compile errors/typos when a real assertion failure was expected. |
| **Writing too much at once** (test or production). | Cap each step at one logical behavior (~5 lines). One logical change per cycle (Searls). |
| **Chasing elegance during Green.** | In Green, permit Fake It / hard-coding; defer all cleanup to Refactor. |
| **Adding functionality during Refactor.** | Refactor = structure only. Any new behavior requires a fresh Red. |
| **Refactoring on red / skipping the refactor step.** | Refactor only when the full suite is green; never end a cycle without the refactor pass (the most common way to screw up TDD — Fowler). |
| **Fixing forward when a refactor breaks a test.** | Revert the refactor, return to the last green state, then retry in a smaller step. |
| **Over-generalizing from one example.** | Abstract only on the second example (Triangulate); one example → Fake It with a constant. |
| **Horizontal slicing / big-bang integration.** | Always slice vertically, end-to-end; integrate continuously via the acceptance loop. |
| **Big design up front.** | Start with a walking skeleton; let architecture emerge under test pressure. |
| **Gold-plating / speculative edge cases.** | Implement only what a current failing test demands. |
| **Slices too large to estimate/test/deliver, or with no value.** | Apply INVEST; reject any slice that isn't Small, Testable, and Valuable. "If a story does not have discernable value it should not be done. Period." |
| **Coverage-chasing without proof it works** (Searls' "local maximum"). | Treat a green end-to-end acceptance test — not unit coverage — as the definition of done. |
| **Outer test reaching into internal code.** | Acceptance tests must drive the system only through real external endpoints. |
| **Over-mocking that couples tests to structure.** | Mock collaborators to design protocols, but watch for brittleness; prefer state/behavior balance and prune mock tests when they impede refactoring. |
| **Treating acceptance tests as an afterthought.** | Write the failing acceptance test *first*, at the start of each slice, as the goal and progress meter. |
| **Analysis paralysis / getting the whole design right up front.** | Let a thin slice and its failing test drive the next step; downshift step size when stuck rather than over-planning. |

---

## 8. Rules of Engagement — Imperative Checklist for the Automated Agent

Follow these literally. Each is an executable instruction.

**Per feature (outer loop):**

1. Decompose the feature into thin **vertical** slices. Reject any horizontal (layer-only) slice.
2. Validate each slice against **INVEST**. Reject slices that are not Small, Testable, or Valuable.
3. For a brand-new system, build the **walking skeleton** first: thinnest end-to-end slice that automatically builds, deploys, and tests through real infrastructure.
4. Maintain a **living test list** for the slice; pick tests that drive quickly to the salient design points.
5. Start the slice by writing **one failing acceptance/e2e test** through real external endpoints, in the user's language. Run it; confirm it fails for the right reason.

**Per behavior (inner loop):**

6. **THINK:** Choose the single smallest next testable behavior that advances the acceptance test.
7. **RED:** Write one small failing unit test (~5 lines). Run it. **Watch it fail.** Confirm the failure reason and that the diagnostic is readable. If you cannot articulate why it fails, stop and rethink the requirement.
8. **GREEN:** Write the **minimum** code to pass — Fake It / hard-code if unsure. Run the full suite; confirm green. Do **not** implement anything no test demands.
9. **REFACTOR (only on green):** Remove duplication, fix names, extract collaborators. Re-run tests after **each** small change. If a refactor reddens the bar, **revert it** — never fix forward. Add **no** new behavior here.
10. **Step sizing:** Use Obvious Implementation when confident; Fake It when unsure; Triangulate (require a second example) before abstracting. On any **unexpected red**, downshift to smaller steps.
11. Repeat 6–10, working **inward from the boundary**, mocking not-yet-built collaborators, until the acceptance test can pass.

**Closing the slice:**

12. Re-run the **acceptance test**. If red, you're missing a piece — return to the inner loop. If green, the slice is done.
13. **Outer refactor:** with the whole suite green, clean up across module/boundary scope.
14. Run the **full suite** before any checkpoint/commit. Commit only on green. (If working solo across sessions, you may deliberately leave one test red as a resume marker — but never commit/check-in red.)
15. Never delete a test if it would reduce confidence; prune only truly redundant tests.
16. **Done is defined by a green end-to-end acceptance test**, not by unit-test coverage. Never trade global correctness for local coverage.

**Invariants that must hold at all times:**

- No production code exists without a test that failed first. *(Beck rule 1)*
- The bar is green before and after every refactoring. *(Refactor only on green)*
- No new behavior is ever introduced during a refactor. *(Refactor = structure only)*
- Every new test has been observed to fail for the correct reason. *(Never skip red)*
- Duplication is eliminated before the cycle closes. *(Beck rule 2)*
- When stressed or surprised by red: **run the tests more, and shrink the step.** *("transmuting fear into boredom")*

---

## Sources

- James Shore, *Red-Green-Refactor* (jamesshore.com, 2005).
- Kent Beck, *Test-Driven Development by Example* (via Stanislaw's page-cited notes).
- Martin Fowler, *Test Driven Development* & *Self Testing Code* (martinfowler.com bliki).
- Freeman & Pryce, *Growing Object-Oriented Software, Guided by Tests* (GOOS).
- Alistair Cockburn, *Walking Skeleton* (Crystal Clear).
- Humanizing Work, *Guide to Splitting User Stories*; AgileForAll, *INVEST*.
- Emily Bache, *Outside-In development with Double Loop TDD*; Samman Coaching, *Double-Loop TDD*.
- Khalil Stemmler, *Introduction to TDD*; Justin Searls, *Dual-loop BDD is the new Red-green TDD*.
