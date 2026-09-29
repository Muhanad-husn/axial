# #856 Wikidata reconciliation pass, 2026-09-29

**Command:** `uv run --project D:/axial-856 axial names wikidata`, run from
`D:/axial-runs` (branch `feat/856-wikidata-qids`), detached via `launch.ps1`.
Cost $0 (free public reconciliation API, `wikidata.reconci.link`). Every
response is cached in `data/names/wikidata/responses.jsonl` (3,123 lines);
a re-run makes no calls.

## Counts

| | |
|---|---|
| band (names in 5+ sources) | 1,343 |
| surfaces reconciled (canonicals + aliases) | 3,123 |
| names resolved (service's own `match` flag) | **482 (35.9%)** |
| names with 2+ matched surfaces (a test of the merge) | 217 |
| of those, all surfaces on one QID (agrees with merge) | **191 (88.0%)** |
| `merged_apart` (one node, two QIDs) | 26 |
| `kept_apart` (two band nodes, one QID) | 14 |
| precision, 60-name seeded sample (`precision_sample.txt`) | 57/60 right |

By kind: person 44%, institution/group 40%, period 40%, place 36%, work 36%,
event 30%, concept 17%, movement/religion 16%.

**Canary:** `Ba'th Party` resolves to Q179933 and agrees: `Ba'th Party`,
`Ba'ath`, `Ba'th party`, `Baʿth`, `Baʿth Party`, `Baʿth party` all matched
Q179933. `Baath Party` itself came back unmatched (a tie at score 100 between
Q179933 and Q797513) but rides on the node's QID. `Ba'thist` resolves to
Ba'athism (Q2582421).

## What the disagreements are

- **`merged_apart` (26) is mostly Wikidata, not the merge.** 12 are bare
  surnames the service matched to a different person (`Hechter`, `Kohli`,
  `Makdisi`, `Krasner`, `Gurr`, `Ertman`, `Nairn`, `Bendix`, `Crone`,
  `Leenders`, `Brubaker`, `Malešević`). The canonical wins, so those nodes
  carry the right QID. About 5 are real merge errors: `'Abdallah` (Laroui,
  Amir Abdallah and Öcalan on one node), `'Ahl-il-ʿUd`, `'Anaza` (with
  `Badza`), `'like-over-like' principles of legitimacy` (a grab-bag),
  `iltizam` (with `Azzam`). The rest are singular/plural or narrower items
  on a correct node (`Shia Islam` / `Shia Muslims`, `Syrian Army` /
  `Syrian armed forces`).
- **`kept_apart` (14) is mostly real merge misses:** `US` / `USA` /
  `United States`, `Clifford Geertz` / `Geertz`, `Gulf States` / `Arab Gulf
  States`, `Islamic world` / `Muslim world`, `Security Council` / `United
  Nations Security Council`. A few are Wikidata over-joining (`two world
  wars` onto WWII, `Medieval Europe` onto the Middle Ages).

## A looser acceptance rule, measured and rejected

Accepting the canonical's top candidate whenever it scores 100 would resolve
1,151 (85.7%), but the audit sample carries confident nonsense:
`revolution` -> Wii, `Union` -> European Union, `American` -> American Lake,
`absolutism` -> universality, `Miller` -> Arthur Miller. The service's own
`match` flag stays.

## Incidents

1. First launch died at 40/3,123 with `403 Forbidden`. Cause, found on the
   third launch: typed Q1190554 (occurrence, the issue's event type) the
   service answers 403 to every query; it fails parsing that type's subclass
   tree. Events now go untyped (right item first for the Six-Day War, the
   Hama massacre, the Arab Revolt). The first launch's console was
   overwritten by the second; the second (`console.log`) spent 65 minutes
   in backoff on the same batch and ended with the same 403; the third
   (`console-3.log`) completed, exit 0, in 56 minutes. One record per
   launch is in `run.jsonl`.
3. Materialize afterwards (`materialize.log`, exit 0): `notes.db` carries
   482 QIDs over 47,584 names.
2. Places typed Q56061 (the issue's type) matched `Europe` to the European
   Union; Q2221906 (geographic location) is used instead.

## Next steps

- Founder: the 5 real merge errors and ~10 real merge misses above are the
  first concrete list for narrowing the LLM merge (the issue's follow-up).
- Done 2026-09-29 after #868 merged: materialize re-run here, and
  `index.json`, `wikidata/` and `notes.db` copied to the live data.
