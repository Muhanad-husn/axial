# The relational-join ceiling: is retrieval a JOIN failure, not a ranking failure?

2026-08-04. Offline measurement, no paid model calls, no product code changed.
data/answers/*.jsonl (6,166 interrogation records over 31 sources, the same
notes the vault renders) loaded into an in-memory stdlib sqlite3 database:
notes, note_names (note -> resolved canonical), note_citations,
note_arguing_against / note_arguing_against_conservative (note ->
free-text opposition target -> resolved canonical, when one resolves), plus
sources (the 31 corpus texts author/title/date). Name resolution reuses
the shipped code exactly: axial.query.names._build_name_layer,
canonical_for_surface, and fold_surface_form (the #642 transliteration
fold), never re-derived. Build + query scripts:
scratchpad/relational_join.py, scratchpad/analyze2.py (not committed --
scratch, per the task).

## Bottom line

| Question | Answer |
|---|---|
| Join ceiling vs the prior 4.7% | 44.0% of arguing_against targets resolve to at least one other note (conservative, honest match). A looser match reaches 93.4% but is mostly noise (see below). |
| Cross-source opposition pairs | 43,101 high-confidence (A,B) pairs where a person/work canonical ties them, across 343 distinct scholars/works. A raw, hub-inflated count is 127,776. |
| Is the door layer (find_names/get_name) subsumed by SQL over these tables? | Yes -- reproduced below with the actual queries and matching row counts. |
| Strongest honest negative | Even at the honest match rate, 56.0% of targets (6,096 of 10,897) resolve to nothing -- they are prose descriptions of a position with no distinctive noun phrase the name index captures, and no amount of relational normalization joins free text to free text without semantic matching, which is out of scope for a table. |

## 1. The join ceiling

Two matching modes, both using the real alias/fold layer:

- Permissive: any surface form (canonical or alias) found as a whole-word
  phrase in the target text, including single-token forms.
- Conservative: only surface forms of >=2 tokens (a real noun phrase).

Restricting to >=2 tokens matters: spot-checking the permissive match turned
up single-token false positives straight from the corpus's own noisier
one-word canonicals (NER noise, not a join-logic bug): "the notion of Free
French rule" resolving to the canonical Rule, "Goodwin's state-centered
paradigm of low ... capabilities" resolving to Low, "many of his
contemporaries" resolving to His. The conservative number is the one to
trust.

| Metric | Denominator | Permissive | Conservative (trust this one) |
|---|---|---|---|
| Notes with >=1 arguing_against answer | 6,166 notes | 4,663 (75.6%) | same |
| Distinct (note, target) pairs | -- | 10,897 | 10,897 |
| (b) resolves to >=1 name in the index | 10,897 targets | 10,225 (93.8%) | 5,051 (46.4%) |
| (a) resolves to >=1 OTHER note (a note whose own names carries that canonical) | 10,897 targets | 10,178 (93.4%) | 4,800 (44.0%) |
| (c) resolves directly to one of the corpus's 31 source-authors | 10,897 targets | 39 (0.4%) | 28 (0.3%) |

Prior measurement (memory: DEC-60/#568): 4.7% of 10,883 targets joined to
a name page, via exact/alias/fold string equality only (no phrase
containment). Extending to phrase-level containment with the same #642 fold
raises the honest ceiling roughly 9-10x, to 44-46%. That gap is real: the
prior number under-measured because it required the entire target string to
equal a name; most targets are full sentences describing an argument, with
the actual named entity as a sub-phrase (Ernest Gellner inside "Gellner's
and Popper's view that eugenics is an aberration...").

Kind breakdown of the conservative resolutions (why the join works when it
works): concept noun phrases dominate (welfare state, ethnic conflict,
class struggle), not proper names -- 42.5% of all targets resolve to a
concept phrase, only 2.8% to a person, 9.5% to a cited work. The join
surfaces conceptual disagreement far more than "who cited whom."

## 2. Cross-source opposition pairs

For every arguing_against target A resolved (conservative) to canonical c,
every OTHER note B (different source_id) whose own names answer carries c
is a candidate opposition partner -- A opposes something that is literally
what B's passage is about.

| Count | Value |
|---|---|
| Raw cross-source (A,B) pairs | 127,776 |
| Distinct opposing notes (A) reaching >=1 cross-source B | 2,740 / 3,241 (84.5%) |
| Share of raw pairs from the top 10 hub canonicals (United States, Middle East, World War I, Civil War, nation-state, Michael Mann, French, nineteenth century, West, World War II) | 86,787 / 127,776 (67.9%) |
| High-confidence pairs (canonical is a named person or cited work, not a place/period hub) | 43,101, across 343 distinct scholars/works |

The raw count is hub-inflated the same way #522 found name_neighbors to be:
two notes both mentioning "the United States" is not disagreement. Filtering
to person/work canonicals removes the geography and gives a defensible
scholarly-disagreement count.

Real examples (conservative join, person/work canonical, cross-source):

- A (hall-2006): "Mann's conclusion that ideological power declined after
  the Reformation does not follow, because losses in extensive church power
  were counterbalanced by gains in intensive power..." -- arguing against
  Michael Mann -- B (mann-v3-2012): Mann's own globalization claim.
- A (smith-2009): "Modernists wrongly marginalize ethnicity..." -- arguing
  against Ernest Gellner -- B (gellner-1981): Gellner's own note.
- A (smith-2009): same note, arguing against Benedict Anderson -- B
  (white-2011): a note that discusses Anderson's account of minorities and
  majorities.
- A (smith-2009): "an ethno-symbolic approach places ethnic phenomena at
  the centre..." -- arguing against Michael Mann -- B (hall-2006): "Mann's
  theory of state power continues to generate fruitful insights..."

## 3. Three historian queries the door layer cannot answer

All three ran as plain SQL joins over notes / note_names /
note_arguing_against_conservative / sources. find_names/get_name/
who_argues_against each walk exactly one relation; none can chain two.

Q1 -- "Positions on X held by authors who disagree with Y"
(X = the state, Y = Michael Mann):

    SELECT DISTINCT n.chunk_id, n.source_id, n.position
    FROM notes n
    JOIN note_names state_n ON state_n.chunk_id = n.chunk_id AND state_n.canonical = 'the state'
    WHERE n.source_id IN (
      SELECT DISTINCT source_id FROM note_arguing_against_conservative
      WHERE resolved_canonical = 'Michael Mann'
    );

1 row (Malesevic 2010, historical-sociological) -- a small but real answer;
find_names('the state') alone cannot filter by who its 40 authors argue
against, and who_argues_against('Michael Mann') alone cannot tell you what
those authors think about the state.

Q2 -- "Claims about X made only by sources published after Z"
(X = Civil Wars, Z = 2000):

    SELECT n.chunk_id, n.source_id, s.date, n.claim
    FROM notes n
    JOIN note_names nn ON nn.chunk_id = n.chunk_id AND nn.canonical = 'Civil Wars'
    JOIN sources s ON s.source_id = n.source_id
    WHERE CAST(s.date AS INTEGER) > 2000;

15 rows. get_name('Civil Wars') returns every member note in the page's own
order; it carries no source_meta.date at all, so a caller cannot filter by
publication year without reading every member note's own source metadata by
hand.

Q3 -- "Names co-occurring in notes that argue against the same target"
(target = Michael Mann):

    SELECT nn.canonical, COUNT(DISTINCT nn.chunk_id) AS n
    FROM note_arguing_against_conservative aa
    JOIN note_names nn ON nn.chunk_id = aa.chunk_id
    WHERE aa.resolved_canonical = 'Michael Mann' AND nn.canonical != 'Michael Mann'
    GROUP BY nn.canonical ORDER BY n DESC LIMIT 10;

10 distinct names, top hits IEMP model (8 notes), Europe (8), The Sources of
Social Power (7), Joseph Bryant (5), Ernest Gellner (5). name_neighbors
computes co-occurrence for one name across the WHOLE corpus, never
conditioned on a third relation (arguing_against) at all -- this specific
intersection has no tool today.

## 4. Is the door layer subsumed?

Yes. find_names's group-1 literal tiers (exact/alias/folded/contains, ranked
work-last, then source_count desc, member_count desc, canonical asc --
axial.query.names._rank_group_one) reproduce as one GROUP BY over
note_names:

    SELECT nn.canonical, nn.kind,
           COUNT(DISTINCT nn.chunk_id)  AS member_count,
           COUNT(DISTINCT nn.source_id) AS source_count
    FROM note_names nn
    WHERE nn.canonical LIKE '%French Mandate%'
    GROUP BY nn.canonical, nn.kind
    ORDER BY (nn.kind = 'work'), source_count DESC, member_count DESC, nn.canonical ASC;

Top hit: French Mandate (period) -- member_count 40, source_count 8 --
matching the production door slate's own top result for this query
(issue #632's own worked example).

get_name is a JOIN:

    SELECT n.chunk_id, n.source_id, s.author, s.date, n.claim
    FROM note_names nn
    JOIN notes n ON n.chunk_id = nn.chunk_id
    LEFT JOIN sources s ON s.source_id = n.source_id
    WHERE nn.canonical = 'Ernest Gellner';

208 member rows for Ernest Gellner, same total the production name page
carries.

Both tools are a strict special case of a table the relational store already
holds. Nothing about find_names/get_name requires the flat 49,674-page file
layer -- they need note_names, one index.

## 5. Honest negatives -- what the relational store does NOT fix

1. The permissive join is not usable as-is. Naive whole-word containment
   against the corpus's own 49,555-canonical index inflates to 93.8% by
   matching single common words (Rule, Main, Low, His, French, Western)
   against junk single-token "canonical" entries that are NER artifacts, not
   real doors. That is a corpus/name-index quality problem inherited from
   Phase A, not something a JOIN fixes -- restricting to >=2-token phrases is
   a mitigation, not a cure ('The Great' still falsely catches "Great
   Recession"/"Great Divergence").
2. 56% of targets stay genuinely unjoinable at any normalization. They are
   prose descriptions of an argument or school of thought with no
   distinctive noun phrase the name index carries at all -- "the metaphor
   that criminals using state cover are an external cancer", "the single
   right-left continuum of regime typologies", "tactical uses of
   victimhood". The relation (arguing_against) is recorded; there is
   nothing to key a JOIN on. Closing this gap needs semantic matching
   (embeddings or a model), which is outside what a relational
   normalization pass can do.
3. Cross-source opposition pairs are hub-dominated. 68% of the raw pair
   volume comes from just 10 place/period/nation canonicals (United States,
   Middle East, World War I...). "Both notes mention the United States" is
   not disagreement; the same hub problem #522 found for name_neighbors.
   The 43,101 high-confidence (person/work-only) count is the trustworthy
   one, not the 127,776 raw count.
4. Resolution directly to a corpus source-author is nearly empty (0.3%,
   28-39 pairs). arguing_against targets almost never name one of this
   31-source pilot corpus's own authors; they target the wider literature
   (Weber, Durkheim, Foucault -- none of whom is a source here). That axis
   the founder asked about (c) is real but thin by construction of a
   31-source corpus, not a join defect.
5. This is still string matching, not entity resolution. A target that
   paraphrases an author without naming them ("the notion that a European-
   style independent bourgeoisie emerged in the Arab world" -- no scholar
   named) is invisible to any table-based join, permissive or conservative.

## Reproduction

scratchpad/relational_join.py builds the tables from data/answers/ and
data/names/ and dumps intermediate JSON. scratchpad/analyze2.py loads that
JSON into sqlite3 and runs every measurement above. Both are throwaway (per
the task) and were run from D:/axial so data/ resolved to the real corpus.
Total build+resolve time: ~6 minutes (dominated by the containment-match
scan, not sqlite).
