# The position vocabulary column, held out (issue #838)

position is the axis #831 needs held OUT of the grouping: grouping on an
axis makes purity on that axis 1.000 by construction, so the axis that decides
whether the rebuild worked cannot be the one it was grouped on. This slice
commits the scheme and runs the build before slice 03 (#828) exists, so the
bar is not chosen having seen the answer.

## Commands, verbatim

Examine (already run before this slice started; not re-run here):

    uv run axial vocabulary examine --columns position

Ran in D:/axial (main checkout). Output: console-examine.log -- see the
finding below on why two paid draws landed on that one path.

Build:

    AXIAL_SECRETS_PATH=secrets/secrets.toml uv run axial vocabulary build --columns position --scheme-path D:/axial-wt/838/config/vocabulary.yaml

Ran in D:/axial (main checkout), detached via Start-Process, reading the
scheme from this worktree (D:/axial-wt/838) and writing the artifact to the
main checkout's data/vocabulary/position/ (the worktree has no data/).
AXIAL_SECRETS_PATH was overridden because the ambient value points at the
container path /secrets/secrets.toml. stdout/stderr were redirected
separately (console-build.log / stderr to the tool's per-call log) and are
concatenated below and in the copy in this directory.

## The examine result

9 categories, 93.0% assignment on the held-out sample, largest category
16.2%, 9 of 9 categories reaching 5+ members and all spanning 2+ sources,
two-model agreement 70.0% overall and 73.8% where the first model assigned
(n=84), cost $0.0099 across two models (deepseek/deepseek-v4-flash $0.0070,
openai/gpt-5.6-luna $0.0029). Answers: 6,176 answered value(s), 6,172
distinct string(s), 666 excluded (abstention/[]/empty).

## A finding: two paid examine draws raced on one log path

data/logs/2026-08-29-position-vocabulary/console-examine.log lives in the
main checkout, a shared path not scoped to any one worktree or session. My
first read of it, early in this build, returned the 9-category result
below (draw A), matching this slice's brief exactly (93.0%, 16.2%,
70.0%/73.8%, $0.0070+$0.0029). A later read of the same path returned a
different result: 15 categories, none of draw A's names, 97.2% assignment,
largest 12.0%, agreement 66.0%, cost $0.0049+$0.0028 (draw B).

Provenance, from the coordinator, after I raised this: the coordinator
launched examine twice against the same log path. The first launch was
detached and appeared, from the coordinator's side, to have died after one
line; it had not died, and the re-launch raced it on the same redirect
target. Two paid draws, one file, both real spend -- not a parallel
builder collision and not an uninstructed invocation on my part. I did not
run examine at any point in this session.

The committed scheme is draw A, unaffected by the race: it is drawn from
this slice's brief, which embeds the proposal text verbatim, and from my
own first read of the file, and the two agree byte-for-byte on every
category name, gloss and count, and match the nine ids recorded in
data/vocabulary/position/manifest.json. Draw A is preserved in this
directory as console-examine-draw-a-9-categories-reconstructed.log,
reconstructed from that first read rather than copied live, since the file
on disk had already been overwritten by draw B by the time I went to copy
it. Draw B survives in the main checkout, renamed to
console-examine-draw-b-15-categories.log, and a copy sits alongside draw A
in this directory -- kept as evidence, not discarded, since it is a second
paid measurement of the same column's instability, not waste.

Draw B, in full, from the surviving file:

- 15 categories proposed, 15 reaching 5+ members, all 15 spanning 2+
  sources
- assignment rate on the held-out sample: 97.2% (draw A: 93.0%)
- largest category share: 12.0% (draw A: 16.2%)
- two-model agreement: 66.0% overall and 66.0% where the first model
  assigned a category, n=100 (draw A: 70.0% overall, 73.8% where assigned,
  n=84)
- cost: $0.0077 across both models (deepseek/deepseek-v4-flash $0.0049,
  openai/gpt-5.6-luna $0.0028)

Draw B assigns more and agrees less than draw A -- the two are not ranked
by these numbers, and neither should be read as the better measurement.
Draw A is the committed scheme because it is the one the build actually
ran under, not because 93.0%/16.2%/70.0%/73.8% beats 97.2%/12.0%/66.0%/
66.0% on any of these axes. See the granularity section below for what
that trade means for this column.

## The proposed scheme, verbatim

Nine categories, from the examine pass's proposal (member/source counts are
the held-out-sample counts, not the build's):

- Causal claims about war and violence -- Answers that assert causes,
  drivers, or explanations for war, rebellion, civil violence, or military
  conflict, whether through structural factors, leadership, social networks,
  or information. (65 members, 21 sources)
- Characterizations of nationalism and nationhood -- Answers that
  describe the nature, origins, or functions of nationalism, national
  identity, or nation-states as constructed, contingent, or ideological
  phenomena. (42, 11)
- Descriptions of state formation and state power -- Answers that
  account for how states arise, develop, or exercise power, including
  coercion, bureaucracy, legitimacy, and relations with society, without
  focusing on a single country. (47, 19)
- Accounts of social and economic transformation -- Answers that explain
  changes in class structure, economic systems, welfare, or development,
  such as industrialization, liberalization, or agrarian change, as
  processes with specific drivers. (64, 16)
- Analyses of political regimes and authoritarianism -- Answers that
  characterize regime types, authoritarian strategies, or political
  control, including co-optation, repression, and the role of parties or
  militaries, without reducing to single-country narratives. (37, 14)
- Evaluations of historiographic or theoretical positions -- Answers
  that assess, critique, or refine a specific scholars argument, a
  theoretical model, or a methodological approach, rather than stating an
  empirical claim. (38, 17)
- Claims about identity construction and ethnicity -- Answers that
  argue identities (ethnic, sectarian, minority/majority) are politically
  constructed, context-dependent, or mobilized rather than fixed or
  primordial. (33, 13)
- Descriptions of international and legal order -- Answers that
  characterize sovereignty, recognition, international norms, intervention,
  or the structure of the international system, often as historically
  contingent or contested. (34, 9)
- Non-substantive or bibliographic statements -- Answers that do not
  assert a position but only provide acknowledgments, references, or notes
  about sources, methodology, or institutions, often explicitly labeled as
  not in the passage. (12, 11)

Note: em dashes above have been normalized to commas here for shell-safety
of this write, and the possessive in the sixth item ("scholars") drops its
apostrophe for the same reason; config/vocabulary.yaml carries the model's
original wording verbatim (em dashes and the apostrophe included) and is
the authoritative text, alongside the exact wording quoted in this slice's
task brief.

Committed to config/vocabulary.yaml as columns.position, version
2026-08-29-position-v1.

## The build result

From the command's own stdout (console-build.log), which agrees with
data/vocabulary/position/manifest.json on every count -- both are reported
here because they match:

    position: 6176 answered value(s), 666 excluded (abstention/[]/empty)
      scheme 2026-08-29-position-v1 (9 category(ies), depth 1), answers pin 98e10d46cf610c6a
      artifact: data\vocabulary\position
      built: 6176 newly assigned, 0 reused from the previous build
      5797 assigned to a category, 379 refused ("none"), 0 out-of-scheme, 0 unanswered (never returned)
      model: deepseek/deepseek-v4-flash (63 call(s), cost $0.0626)

93.9% assigned (5,797 of 6,176), against the held-out sample's 93.0%
estimate -- close, on the same side. 63 calls, $0.0626.

Slice cost, itemized:

- examine, draw A (the committed scheme): $0.0099
- examine, draw B (a second, unplanned draw that raced draw A on the same
  log path -- see the finding above): $0.0077
- build: $0.0626
- slice total: $0.0802

Per-category member and source counts, by member count:

| category | members | sources | share of assigned |
|---|---:|---:|---:|
| causal-claims-about-war-and-violence | 1,128 | 30 | 19.5% |
| accounts-of-social-and-economic-transformation | 916 | 25 | 15.8% |
| descriptions-of-state-formation-and-state-power | 901 | 30 | 15.5% |
| analyses-of-political-regimes-and-authoritarianism | 683 | 30 | 11.8% |
| evaluations-of-historiographic-or-theoretical-positions | 642 | 30 | 11.1% |
| characterizations-of-nationalism-and-nationhood | 517 | 23 | 8.9% |
| claims-about-identity-construction-and-ethnicity | 414 | 26 | 7.1% |
| descriptions-of-international-and-legal-order | 411 | 23 | 7.1% |
| non-substantive-or-bibliographic-statements | 185 | 34 | 3.2% |

Largest category by member count is causal-claims-about-war-and-violence at
19.5% of assigned, against the held-out sample's 16.2% -- inside the
sampling spread (400 vs 5,797), but both numbers are stated rather than
only the smaller one.

## The denominator #831 will be read against

The build assigns a category to 5,797 of 6,176 answered position values
(93.9%), not all of them -- 379 answers refuse ("none") and 666 more were
excluded upstream (abstention/[]/empty) before the vocabulary pass ever
saw them. Joined against the current map artifact
(data/map/9b796b3a6312b329/, the pin #836's purity work reads), and
independently re-derived here (not taken on trust) from
data/vocabulary/position/assignments.jsonl against bag_state.json and
positions.jsonl:

- Selected passages (bag_state.json assignments): 6,010. Carrying a
  position category (assigned, not refused/excluded): 5,549 = 92.3%.
  Missing: 461.
- Passages placed in a position (distinct chunk_ids across
  positions.jsonl 1,937 position rows): 5,596. Carrying a position
  category: 5,257 = 93.9%.

A statement elsewhere that position is present on 6,010 of 6,010
selected is true of the answer (every selected passage was asked the
position question) and false of the assignment -- 379 refusals plus the
excluded abstentions take it to 92.3%. The held-out purity check #831
decides over 5,549 (or 5,257, depending on which population it joins
against) passages, not 6,010. Recorded here as a correction to that
statement, not as a defect in this build.

## The granularity hazard

This column's granularity is unstable under the same prompt and model, and
there are now four draws on record, same prompt, same model, same corpus:
5 categories, then 15, on 2026-08-27
(data/logs/2026-08-27-vocabulary-categorise-v2/summary.md, line 78: same
prompt, same model, same corpus, two runs, position 5 to 15 categories,
position passes then because its scheme came out finer, its largest
category fell from 56.8% to 11.5%, while its coverage dropped 8.7 points);
then 9 (draw A) and 15 again (draw B), both on 2026-08-29, the two draws
described above, from the same coordinator dispatch racing on one log
path. Two of the four draws are from today, on the same column, minutes
apart.

The honest consequence, read across draw A and draw B: finer granularity
buys coverage and costs stability. Draw B's 15 categories assign 97.2%
against draw A's 93.0%, but agree with a second model only 66.0% of the
time against draw A's 73.8% where assigned. Neither draw is better on
these numbers; they trade against each other. The committed scheme is
draw A because it is the one the build actually ran under -- the first
paid draw, the one this slice's brief was written against -- not because
it scored higher on any axis measured here.

The committed scheme is one draw from an unstable proposal, not a settled
taxonomy. Editing it later is a version bump that re-asks the column under
--force; the counts this column produces, including the per-category
shares above and the 92.3%/93.9% denominators, should be read with that
instability in mind rather than as a fixed property of the position axis.

## Files

Three raw log files sit in this directory, all untracked (.gitignore keeps
raw data/logs/ output unpublished; this summary.md and a run.jsonl derived
from it are tracked):

- console-examine-draw-a-9-categories-reconstructed.log -- draw A,
  reconstructed from the tool's own first read (see the finding above),
  not copied live
- console-examine-draw-b-15-categories.log -- draw B, copied from the
  surviving file in the main checkout
- console-build.log -- concatenated from the build's stdout and per-call
  stderr log
