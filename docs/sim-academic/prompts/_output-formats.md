# Output formats — attach this file to every run

*Simulated-academic development path. Every output you produce must follow the exact
shapes below so it drops straight into the build with no reformatting. Produce each
output as a **downloadable file** (or, if the interface cannot attach files, a single
fenced code block per file that the operator will save under the given name).*

There are three output types. A research/hard-case persona produces types **1 and 2**.
A gold labeler produces type **3** only.

---

## Provenance — required on every output

- **Research briefs (YAML):** the loader rejects any key it does not know, so
  provenance goes in **comment lines** at the top of the file (lines starting with
  `#`). Do not add provenance as YAML keys.
- **Hard cases and gold labels (JSON):** provenance goes in a `_meta` object.

Provenance fields (fill every one):
`origin: simulated`, `model`, `persona` (e.g. `P1`), `reasoning_mode_confirmed`
(the deep-research / extended-thinking mode you ran with), `date` (YYYY-MM-DD),
`path_version: sim-v1`.

---

## 1. Research brief — one YAML file per question

Shape is exactly `{case, request}` plus an optional `lens`. **Omit `lens`** — the
lens library is not built yet, so an unknown lens value would fail validation.
Produce **5–6 briefs**. `case` is the polity or polities in plain words; `request` is
the analytical question. Both must be non-empty. Name each file
`<persona>-NN.yaml` (e.g. `P1-01.yaml`).

```yaml
# origin: simulated
# model: <model name>
# persona: P1
# reasoning_mode_confirmed: <mode>
# date: 2026-07-21
# path_version: sim-v1
case: "Syria, 2011–2024"
request: "Did the civil war build state capacity anywhere it consolidated control, or only hollow it out? Answer in infrastructural-power terms."
```

Keep each `request` to one sharp question a specialist would actually put to this
corpus. Rough phrasing is fine; edge and specificity matter more than polish.

---

## 2. Hard case — one JSON file per case (the answer-quality referee)

These are the *hard* version of your questions: the cases you think an honest system
should struggle with. Reference sources **by `source_id` only** — never paste source
text. Every `source_id` must be one of the 30 in the attached
`corpus-bibliography.md`. Produce **3–5 cases**. Name each file `<persona>-NN.json`.

Each case is **either** an expected answer with required citations **or** a rubric —
set `answer_kind` accordingly and fill the matching field.

```json
{
  "_meta": {"origin": "simulated", "model": "<model>", "persona": "P1",
            "reasoning_mode_confirmed": "<mode>", "date": "2026-07-21", "path_version": "sim-v1"},
  "case_id": "P1-01",
  "question": "Did the civil war build or hollow out Syrian state capacity?",
  "answer_kind": "expected_answer",
  "expected_answer": "A strong answer distinguishes infrastructural from despotic power, and shows...",
  "required_citation_source_ids": ["mann-sources-of-social-power-v2-ec759675dcbd", "do-civil-wars-make-or-break-states-4faeb528594d"],
  "rubric": [],
  "instant_dismissal_criteria": ["Treats 'the state' as a single actor", "No long-run baseline"],
  "notes": ""
}
```

For an open question with no single right answer, set `"answer_kind": "rubric"`,
leave `expected_answer` empty, and fill `rubric` with the checklist a good answer must
satisfy. `instant_dismissal_criteria` is what would make you reject an answer on sight.

---

## 3. Gold labels — one JSON file per labeler

You are labeling the attached chunk sheet. For each row (keyed by `chunk_id`) return
the five label fields. **Do not echo `chunk_text` back** — return labels only, keyed
by `chunk_id`. Every value for the four codebook axes must be a valid id from the
attached `codebook.yaml`. Name the file after your model (`glm.json` or `gpt.json`).

- **Label from scratch (arrive empty):** `claim_type`, `theory_school`.
- **Correct the pre-filled guess:** `field`, `empirical_scope`, `polities_touched`.
- `polities_touched` is free text, semicolon-joined (e.g. `"Syria; Iraq"`); use
  `""` if none apply.
- `theory_school` may be `not-applicable` (no theoretical position) or `unlisted` (a
  real school not in the list) — see the codebook definitions before using either.

```json
{
  "_meta": {"origin": "simulated", "model": "<model>", "persona": "neutral-coder",
            "reasoning_mode_confirmed": "<mode>", "date": "2026-07-21", "path_version": "sim-v1"},
  "labels": {
    "<chunk_id>": {
      "claim_type": "state-capacity",
      "theory_school": "state-centered-organizational",
      "field": "state",
      "empirical_scope": "scope:country-case",
      "polities_touched": "Syria"
    }
  }
}
```

Return one entry per row in the sheet. If a row is genuinely unlabelable, still
include its `chunk_id` and put your reason in a `"notes"` string on that entry.
