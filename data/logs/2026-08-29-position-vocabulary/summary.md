# The position vocabulary column, held out (issue #838)

position is the axis #831 needs held OUT of the grouping: grouping on an
axis makes purity on that axis 1.000 by construction, so the axis that decides
whether the rebuild worked cannot be the one it was grouped on. This slice
commits the scheme and runs the build before slice 03 (#828) exists, so the
bar is not chosen having seen the answer.

## Commands, verbatim

Examine (already run before this slice started; not re-run here):

    uv run axial vocabulary examine --columns position

Ran in D:/axial (main checkout). Output: console-examine.log (see note
below on this file's integrity).

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

## A finding: the examine log was overwritten mid-session

data/logs/2026-08-29-position-vocabulary/console-examine.log lives in the
main checkout, a shared path not scoped to any one worktree or session. My
first read of it, early in this build, returned the 9-category result above,
matching this brief's numbers exactly (93.0%, 16.2%, 70.0%/73.8%,
$0.0070+$0.0029). A later read of the same path -- no axial process
visible as running at either check -- returned a different result: 15
categories, none of the 9 names above, 97.2% assignment, largest 12.0%,
agreement 66.0%, cost $0.0049+$0.0028. The request sizes (prompt_chars) were
identical across both reads; only the model's returned content and elapsed
times differed on re-request -- consistent with a second, independent
examine invocation against the same log path overwriting the first
(redirect truncates, does not append), not with a self-consistency retry
inside one process.

I did not run examine at any point. The 9-category scheme committed below
is not affected -- it is drawn from this brief's embedded proposal text and
from that first read, both of which agree byte-for-byte on every category
name, gloss and count. But the file now on disk in D:/axial does not
match either, so the console-examine.log copied into this worktree is
reconstructed from the tool's captured first read of the file, not copied
live from the current (overwritten) one -- the current file on disk would
contradict the numbers in this summary if copied as-is. Whatever produced
the second run spent roughly $0.0077 of real cost not accounted for by this
slice's brief and worth the founder's attention: either a second builder
session collided on this shared log path during a parallel dispatch, or
something else re-ran examine against instructions.

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
estimate -- close, on the same side. 63 calls, $0.0626. Slice total including
examine: $0.0725.

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

This column's granularity is unstable under the same prompt and model:
position returned 5 categories on one run and 15 on another, 2026-08-27
(data/logs/2026-08-27-vocabulary-categorise-v2/summary.md, line 78, quoting
that summary: same prompt, same model, same corpus, two runs, position 5 to
15 categories, position passes now because its scheme came out finer, its
largest category fell from 56.8% to 11.5%, while its coverage dropped 8.7
points). This slice's own examine pass returned 9 (see above), and, per the
finding above, a later, uninstructed rerun against the same log path
returned 15 again with a different coverage/agreement profile. The
committed scheme is one draw from an unstable proposal, not a settled
taxonomy. Editing it later is a version bump that re-asks the column under
--force; the counts this column produces, including the per-category
shares above and the 92.3%/93.9% denominators, should be read with that
instability in mind rather than as a fixed property of the position axis.

## Files

console-examine.log and console-build.log are copied into this directory
(the former reconstructed per the finding above, the latter concatenated
from the build's stdout and per-call stderr log). Both are untracked
(.gitignore keeps raw data/logs/ output unpublished); this summary.md
and a run.jsonl derived from it are tracked.
