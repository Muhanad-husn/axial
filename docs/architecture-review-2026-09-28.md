# Architecture review: structure, indexing, and the schema question

**2026-09-28. A reading of the repository, the data on disk, the decision log
and the run logs. No model call was made for this review. Every number below
is read off `data/` or a committed log.**

> **Ruling, same day (DEC-75).** The founder approved the programme in §8 with
> two amendments, both folded in below. Every name page goes, not only the
> single-source ones: the founder sees them as noise in the graph and nothing
> in the final output draws on them (§8, step 1). And a better map is wanted
> if a considerable option exists; §8 step 6 now names the two levers worth
> paying for and how each is judged before any judged gate is trusted.

## 1. Verdict

The corpus does not need a new structure. It needs one fewer structure and two
small typed layers it never got.

The substrate is right and stays untouched: 6,842 interrogated notes, fourteen
open questions each, free text, roughly $34 to reproduce. Everything
recommended here is a pass over `data/answers` and `data/vault/notes.db`, both
already paid for. The largest single item costs about $1.20.

The over-engineering the founder senses is real and has a precise location.
The system has answered one question, *how do two passages meet*, three times
(shared name, shared stake, shared category) and physically kept all three.
The name layer was demoted to a filter on 2026-08-04 (DEC-62) but its full
apparatus is still built, stored and run. That is where the resources go, and
the decision to stop is already on the books; only the deletion was bundled
with the shelved category rebuild (DEC-74) and fell with it.

On the four questions: the product is already schema-free where that was the
right call (the *values* the model writes), and schema-less where it hurt (the
*types* of relations and the *identities* of entities). An RDF stack is the
wrong remedy. Two RDF vocabularies, adopted as naming discipline inside the
SQLite store that already exists, are the right one.

## 2. What is on disk

| Layer | Size | Rows or files | Cost to rebuild |
|---|---|---|---|
| Interrogation answers | 37 MB | 6,842 notes, 14 fields each | ~$34 |
| Note store `notes.db` | 54 MB | 137,276 name edges, 13,998 `arguing_against` edges, 35,975 citation edges | $0 (materialize) |
| Name pages (vault) | 130 MB | 47,584 markdown files | $0 (materialize) |
| Name embeddings | 536 MB | one vector per surface | $0, local encoder |
| Name merge decisions | 14 MB | LLM merge log | model pass, 36 workers |
| Gather disagreements | 10 MB | 447 entries from 1,910 pages | $4.94 per pass, 36% non-reproducible |
| Argument map | 44 MB | 1,937 positions, 1,472 relations | $0.77 to 0.87, plus $0.35 to 0.41 for relations |
| Derived vocabulary | 11 MB | 3 columns committed, 6,671 assigned on `claim` | ~$0.10 to 0.20 per column |

The name layer's own numbers, from `notes.db` today:

- 47,584 canonical names. **39,498 (83%) appear in one source.** 1,343 appear
  in five or more. The usable band the retrieval work settled on (5+ sources,
  30+ notes) holds **371 names**.
- Name-layer code: about 12,500 lines across `names.py`, `merge_names.py`,
  `query/names.py`, `gather.py`, `gather_eval.py`, `name_candidates.py`,
  `reconcile.py`, `polity_canonical.py`, `materialize.py`, `vault.py` and the
  retrieval loop, of roughly 75,000 non-test lines in `src/`.
- The `name` retrieval arm measured **3.2x dearer and 4x slower** than the map
  arm with no grounding advantage (#809, `data/logs/2026-08-28-layer-comparison/`).

The relation layer's numbers:

- `arguing_against` has 13,998 edges; 7,513 resolve to a canonical name and
  649 of those targets are argued against from two or more books. This is the
  counter-position substrate the charter's Principle IV depends on, and it is
  queryable today only through the note store.
- Citation stance is already typed, by accident of the prompt: `support`
  25,767, `authority` 7,502, `foil` 2,598, and a tail of 108.
- `note_opposed_position`, the table that joins a note's `arguing_against`
  target to a map position (#651), holds **0 rows** on the current pin. The
  residue pass that fills it last ran against an earlier map, so the one
  note-to-map opposition join the store was designed for is empty today.
- The map's 1,472 relations carry **504 distinct free-text labels** ("redirects
  explanation", "narrows scope", and so on). The build prompt says "there is no
  list of allowed relations" by design. The consequence is that nothing can ask
  for *conflicts* or *supports* across the map; a relation is findable only by
  the position it hangs off.

## 3. The diagnosis

The founder names two original decisions: flat indexing, and names as the
share point. Both are correct as history, and both are already reversed in
principle. What remains is the residue of reversing them additively.

**Flat indexing** was the surface-string page. DEC-62 replaced it with
`notes.db`, seven tables, and showed `find_names` is one `GROUP BY` and
`get_name` a plain join over it. The flat vault of 47,584 files still gets
written and still holds 130 MB, and the retrieval loop still carries eight
tools that walk it.

**Names as the join** was the premise that sharing a string is a connection.
The map replaced it with shared stake and measured better on grounding with
fewer sources. The category rebuild then tried to replace the map's own
grouping rule and failed the bar written for it (purity 0.662 against 0.760,
unplaced 8.5% against 6.9%). That failure is about *what the extraction model
reads together*, not about categories as such: 7 of 12 answer columns
categorise cleanly, every category reaching five members crosses books, and
the `claim` column assigns 99.5%.

So the schema question splits into three layers, and each has a different
answer:

| Layer | Has a schema today? | Should it? |
|---|---|---|
| **Questions** (the 14 fields) | Yes. Fourteen fixed predicates per note. | Yes, and it has one. This is the schema. |
| **Values** (what the model writes) | No. Free text, abstention allowed. | No. The closed tags of v0.1 died (D4/D9, `query_by_tag` returned zero). Free text plus post-hoc categorisation is measured to work. |
| **Relations** (edges between notes and between positions) | Partly. `arguing_against`, citation stance, and 504 free labels on the map. | **Yes, small.** A ten-word relation vocabulary is what makes the map queryable by kind. |
| **Identities** (who or what a name is) | No. Folded strings plus an LLM merge that disagrees with itself 13.3%. | **Yes, borrowed.** Entity identifiers exist; this repository re-derives them. |

## 4. Can the system be built without a schema?

It was, and for the values it should stay that way. The evidence is the
repository's own: the v0.1 closed vocabularies produced tags nothing could
retrieve by; the free-text interrogation produced answers that categorise
after the fact at 77% cross-model agreement on `claim` and 82% on `evidence`,
which is the range published LLM-coding studies report. Imposing a scheme at
read time would trade a measured 99.5% assignment for an unmeasured one and
would need the $34 re-interrogation the founder does not want.

Where "no schema" cost the product is not the values. It is the two places a
string was asked to do a type's job: a name standing in for an entity, and a
coined label standing in for a relation kind. Those are cheap to fix and
neither touches the interrogation.

## 5. How a schema is developed here

The process already exists and has run three times: `axial vocabulary examine`
proposes categories from a random sample of a column's answers, a person edits
and commits the scheme to `config/vocabulary.yaml` with a version, and
`axial vocabulary build` assigns every note for roughly ten cents. That is
deductive qualitative coding with a committed codebook and an LLM coder, which
is standard practice, and the file is already SKOS-shaped (`id`, `name`,
`gloss`, `parent_id`, version). The one thing it lacks is a stated home for
each scheme's job, which is what let the category rebuild use a grouping
vocabulary as a bagging rule.

The process for the two missing layers:

- **Relations.** Run `examine` over the 504 labels in `relations.jsonl` exactly
  as it ran over answer columns. Commit ten to fifteen kinds. Seed the list
  from the Argument Interchange Format's three genera (inference, conflict,
  preference) so the top level is standard and the children are the corpus's
  own recurring shapes ("redirects explanation", "qualifies scope"). Assign the
  1,472 relations in one cheap pass, under $0.50. The map build prompt then
  offers the committed list as *examples*, the way the interrogation frame
  does, never as a menu.
- **Identities.** Reconcile the 1,343 names that appear in five or more sources
  against Wikidata through its reconciliation API, and store the QID beside
  the canonical. The other 46,000 names stay as folded strings; they are
  filters over one or two books and nothing joins on them. This replaces the
  LLM merge for exactly the names that matter and settles transliteration
  (Ba'th and Baath are one QID) without a fold rule.

## 6. Open-source ontologies: which, for what

None of these becomes "the schema". Each takes one layer.

| Layer | Standard | What it buys | Cost |
|---|---|---|---|
| Vocabulary format | **SKOS** | `config/vocabulary.yaml` is already `prefLabel`, `definition`, `broader`. An export is one `rdflib` script. Makes the schemes publishable and cross-mappable. | $0 |
| Concept layer (`about`, `uses`, `defines`) | **ELSST** (CESSDA, CC-BY-SA, ~3,400 concepts, politics and sociology) | An off-the-shelf hierarchy for the state, ideology and violence vocabulary. Cross-map derived `about` categories with `skos:closeMatch`; do not replace them. EuroVoc is the alternative. | $0, one mapping pass |
| Entities | **Wikidata** QIDs (people, places, organisations, works, periods) | Entity identity from outside the corpus. Retires the hand-rolled disambiguator for the usable band. | $0, API calls |
| Argument relations | **AIF** (Argument Interchange Format; OWL, RDF and SQL specifications) | Information nodes and scheme nodes with inference, conflict and preference genera. Positions are I-nodes, relations are S-nodes. Gives the top level of the relation vocabulary and a standard export for the map. | <$0.50 for the typing pass |
| Citation stance | **CiTO** (Citation Typing Ontology) | The three stances already emitted map onto `cito:supports`, `cito:citesAsAuthority`, `cito:disagreesWith`. Rename, do not re-extract. | $0 |
| Audit trail | **PROV-O** | Claim to grounds to chunk to model to prompt version, the charter's auditability spine, in a standard shape. Optional; the run logs already hold it. | $0 |

There is no mature open ontology for state formation, ideology or political
violence as *theories*. The bellicist against institutionalist dispute is a
position the corpus holds, and it belongs in the map as positions and typed
relations, not in an imported class hierarchy. Do not build one.

## 7. RDF, RDFS, OWL, SPARQL, SHACL

**Do not adopt a triplestore.** Take the vocabularies, keep the store.

- `notes.db` is already the graph: 6,842 nodes, about 190,000 typed edges,
  seven tables, answered in milliseconds. A SPARQL endpoint over the same
  edges answers the same questions more slowly and adds a service.
- **OWL reasoning is worthless over these edges.** Assignments agree at 61 to
  77% between models. A transitive or inverse property over a graph with one
  wrong edge in four manufactures wrong inferences at scale, and the charter
  forbids unmarked inference. Every cross-source claim must stay a model's
  labelled (b) move over passages it read, never a reasoner's entailment.
- **SHACL** is the one member of the family that fits the problem, as a
  validation contract on records, and `schema.py` plus the Pydantic models
  already do that job in the language the code is written in.
- The three open problems are not store-shaped: which passages an extraction
  call reads together, what kind each relation is, and which strings are the
  same entity. None is solved by a query language.
- A triplestore would be an abstraction with one implementation and a config
  option nobody sets, two of `CLAUDE.md`'s named tripwires.

What RDF does earn: an **export**. Positions and typed relations as AIF,
schemes as SKOS, names with QIDs, citations as CiTO. One script from
`notes.db` and `data/map/`, when a reader outside the product wants the graph.
Nothing upstream changes to make that possible; the typed layers in §5 are
what make it worth doing.

## 8. The programme, in order

None of these re-interrogates. Each is measurable offline before any judged
gate is paid for, and each can be dropped without touching the others.

1. **Retire the name pages entirely; keep the filter; render the map as the
   vault.** Stop writing the 47,584 name pages, delete the ones on disk, and delete
   the code that writes, indexes and walks them (founder's instruction:
   dropped, not disabled).
   Stop the Gather pass and the `name` retrieval arm with its eight walk
   tools. The name embeddings (536 MB) feed only the resolver's similarity tier
   and the LLM merge's blocking step; they go once step 3 has replaced the
   merge for the band that matters. The map arm never reads them. Keep
   `note_names`, `find_names` and `get_name` over the store, and re-point the
   two output readers that still open a page (`answer/source_usage.py`'s
   imbalance disclosure and the run report's `name_pages_touched` count) at
   `notes.db`, where `concept_sources` already answers the same question. The
   Gather output stays on disk as a file.

   Why every page and not the multi-source band: the final output is the
   answer record and the paper, and neither reads a page. Claims cite
   `chunk_id`s; the per-name coverage map is computed from `note_names`; the
   paper is drafted from claims. A page reached the output only through the
   `name` arm, which lost. The 447 Gather disagreements were never audited
   (DEC-55 closed the phase with no quality number). What the founder sees in
   Graph View is 47,584 nodes of which 83% link to one book, drawn around 986
   artifact notes, with the map, the thing the product actually is, absent.

   So the vault is re-formed rather than emptied: one page per position
   (1,937), its argument, its variants, its member passages as links, and its
   typed relations (step 2) as links to other positions. Code writes it, no
   model call, regenerable from `data/map/`. Graph View then draws the
   argument structure. This is slice 09 of the shelved plan, unbundled and
   widened; its evidence (#809) is independent of the failure that shelved the
   rest. `CLAUDE.md`, the README and `PRODUCT.md` §0 and §5 stage 8 describe
   the wiki as notes meeting at name pages, and are rewritten in the same
   change.
2. **Type the map's relations** (§5). One `examine`, one commit, one assignment
   pass. Then the corridor walk in `argmap/ask.py`, which today orders
   positions by bare relation count, can select and order by kind.
3. **Reconcile the usable band against Wikidata** (§5). Store the QID as a
   column on `names`. Measurable: how many of the 1,343 resolve, and how many
   LLM merge decisions the QID agrees with.
4. **Commit `about` and `move` to the vocabulary**; both clear the bar. Use
   all five committed columns as retrieval *filters and addresses* and as
   coverage disclosure, never as the map's bagging rule. Export the file to
   SKOS and cross-map `about` to ELSST.
5. **Profile-directed relation candidates.** The map's relations are computed
   over 340 embedding neighbourhoods, 629 cross-author of 1,472. Generate
   candidate pairs from the vocabulary instead: same `mechanism` category,
   different books, different `position` category. The review of the shelved
   approach called this its strongest section and it was never built (slice
   07). About $0.40 for a relations pass; compare cross-author count and
   relation-kind spread against the current build before judging anything.
6. **A better map: two levers, each a structural experiment before it is a
   rebuild.** Two grouping criteria have been measured and neither won
   outright. Wording bags leave the median position at two passages and
   scatter each mechanism category over a median of 92 bags; category bags
   fell 0.098 below them on held-out purity and declined more passages. Both
   ask the extraction model to read passages together on a basis the author
   never stated. Two levers have not been tried, and both are cheap enough to
   run against the paid-for build with `axial map compare` (D1 to D5) before
   any judged gate is bought:

   - **Opposition-seeded bagging.** Group passages by what their authors said
     they argue against. `arguing_against` resolves to 7,513 targets, 649 of
     them argued against from two or more books, and citation stance marks
     2,598 `foil` citations. Passages that name the same opponent, or cite the
     same work as a foil, are the ones a scholar would read together, and the
     basis is the author's own statement, not wording or a coder's category.
     The wording bag survives only as the inner sizing split, as the category
     plan already allowed. One rebuild, about $1.20. The judgement is D1 to
     D5 against the current build; the property to watch is book-spread (D1),
     because opposition is cross-book by construction, and the risk is D4,
     since passages that argue against nothing (23.6% of notes) need a
     fallback bag.
   - **A stronger extraction model on the same bags.** Every build so far
     extracted with `deepseek-v4-flash` at high reasoning. Position count,
     variant count and the 373 declines may be model-bound rather than
     bag-bound; nobody has checked. Re-run step 3 only, same bags, one
     frontier model, and compare structurally. A few dollars. If the map
     barely moves, the defect is the bagging; if it moves a lot, the cheap
     model was the ceiling and the bagging debate was partly about the wrong
     variable.

   Run the model lever first: it is the cheaper answer to "is the bagging
   the problem" and it changes how the first lever is read. Either lever
   becomes a rebuild only after it clears the bar #831 wrote; the bar stays
   as written.

   One caveat that outranks both: the map densifies with corpus size
   (cross-book arguments 8.7% to 38.4% between builds, k=1.04), and at 35
   sources a sub-hundred-passage improvement is a fact rather than a finding.
   A lever that wins here is re-judged at the next corpus growth before it is
   called settled.

## 9. What I would not do

- Re-interrogate under a fixed scheme. It spends $34 to lose a measured
  property.
- Move to a triplestore or a property graph. Seven thousand nodes do not need
  one, and the reasoning it enables is forbidden by the charter.
- Rebuild the map around categories again. The bar was written before the
  build and the build failed it. The instrument survives for the next idea.
- Merge the tag axes of `schema.yaml` back into the pipeline. They are prompt
  examples now and that is where they belong.
- Delete the answers of any pass. The Gather file, the merge log and the
  category build are provenance; stopping a pass is not deleting its record.

## 10. Decided and open

Decided 2026-09-28 (DEC-75): steps 1 to 5 proceed as written above, step 1
in its every-page form, and step 6's two levers are approved as structural
experiments, not as a rebuild. Each step is a GitHub issue; the issue is the
record from here.

Still open: whether a public export (AIF, SKOS, CiTO) is wanted at all, or
whether the vocabularies are adopted purely as internal naming discipline. The
programme is the same either way; only step 4's export is optional.
