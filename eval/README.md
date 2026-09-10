# Golden-set evaluation

This is a small, fixed evaluation of the RAG pipeline (retrieval, grounded
answering, and abstention) against a hand-authored corpus and question set.
It is not a benchmark suite — it is a calibration and regression tool sized
for an 18-document inbox, and its numbers should be read with that scope in
mind.

## The corpus

`eval/corpus/corpus.json` holds 18 documents: 8 short notes (2-4 sentences,
`type: "note"`) and 10 longer article-style bodies (3-6 paragraphs,
`type: "url"` with a plausible source link).

Fifteen of the eighteen cover topics picked to be deliberately unrelated to
each other — Kafka consumer rebalancing, SQLite WAL mode, HTTP caching,
Postgres index types, asyncio task cancellation, TLS certificate chains,
Docker layer caching, vector database tradeoffs, CAP theorem, sourdough
hydration, espresso grind size, Rust ownership, DNS resolution order, JWT
expiry, and Kubernetes readiness probes.

**A disclosure about the other three.** The first version of this eval
shipped with only those 15 unrelated-topic documents. Every metric came back
1.000 on that first run, and the honest read of that result — spelled out
below — was that unrelated topics make retrieval too easy to be a real test:
the nearest wrong answer to a Kafka question was a paragraph about sourdough,
which no embedding model should ever get wrong. So a *hard slice* of three
near-neighbor documents was added afterward, specifically to give the
benchmark a chance to fail:

- `doc_kafka_producer_batching` — producer-side batching and `linger.ms`,
  sharing vocabulary and domain with `doc_kafka_rebalance` (consumer-side
  rebalancing) while answering a genuinely different question.
- `doc_cdn_cache_invalidation` — CDN edge purging and surrogate keys, sitting
  close to both `doc_http_caching` (client-side HTTP caching semantics) and
  `doc_docker_layers` (a different flavor of "cache invalidation").
- `doc_postgres_explain_analyze` — reading `EXPLAIN ANALYZE` output and
  planner cost estimates, adjacent to `doc_postgres_indexes` (which index
  type to pick) without being the same document.

This is disclosed because it matters to how the result should be read: the
hard slice was added to make the eval *harder*, in the opposite direction
from what would flatter the system, and after the fact — not before, and not
in response to any single question's outcome. It was not added, reworded, or
tuned to recover a particular score; see "Observed results" below for what
it actually did to the numbers. Three new answerable questions (one per new
document, detailed below) were added alongside it. Nothing in the original
15-document set or its 15 questions was touched.

The content across all 18 documents is hand-written rather than scraped or
copied for two reasons. First, it keeps the eval offline and stable — no
network fetch, no risk of a source page changing under us and quietly
invalidating a golden label. Second, for the original 15, topic separation
is what makes item-level relevance judgments unambiguous: if two documents
were both "about Kafka," a hit on the wrong one would be arguably still
relevant, and the eval would be measuring the labeler's patience rather than
the retriever. The hard slice deliberately reintroduces that risk on
purpose, in a controlled way — each of its three questions was written and
checked so that the "wrong" neighbor is a plausible retrieval mistake but a
genuinely incorrect answer, never an arguable one. An eval whose labels are
debatable is worse than no eval, because it produces a false sense of rigor.

## Why relevance is item-level, not chunk-level

`golden.json` labels each question with the *document* ids it should be
answerable from, not the specific chunk id. Chunk-level labels are laborious
to write by hand and they break every time `chunk_target_tokens` or
`chunk_overlap_tokens` changes, or the chunker's sentence-splitting logic is
touched — none of which should invalidate a relevance judgment that's really
about "does this document answer the question." Item-level labels survive a
re-chunk and still measure what matters: did the system surface (and cite)
the right source.

## The questions

`golden.json` has 18 entries: 14 answerable, 4 unanswerable.

The 14 answerable questions are deliberately phrased in different words from
the source text, not lifted from it. For example, the Kafka rebalancing
document says a consumer that stalls "the broker treats identically to a
crash," and the golden question asks "what happens to a consumer's assigned
partitions if it takes too long between poll calls?" — testing whether
embedding similarity finds the right passage on meaning, not on shared
vocabulary. Retrieval that only works on verbatim overlap is not retrieval;
it's string matching, and this corpus is small enough that a naive matcher
would have gotten away with it if the questions had been closer to the text.

The three hard-slice questions follow the same paraphrase rule but add a
second constraint: a plausible wrong document exists in the corpus for each
one, and the question was refined until only one document actually answers
it.

- "why would raising a kafka producer's `linger.ms` setting trade a bit of
  latency for better throughput?" → `doc_kafka_producer_batching`, not
  `doc_kafka_rebalance` — a retriever keying on "kafka" or "broker" alone
  could plausibly reach for the rebalancing document, but it says nothing
  about producer batching, `linger.ms`, or throughput.
- "after updating a static asset on our site, why might visitors keep seeing
  the old version until something is manually purged at the edge?" →
  `doc_cdn_cache_invalidation`, not `doc_http_caching` — the HTTP caching
  document explains browser-side revalidation via ETag, which is a different
  mechanism from a CDN edge purge and doesn't answer "why do I need to purge
  manually."
- "how can I tell whether postgres actually used the index I expected,
  instead of a sequential scan, for a specific query?" →
  `doc_postgres_explain_analyze`, not `doc_postgres_indexes` — the index
  types document explains which index to create, not how to read a plan and
  confirm it was actually used.

The 4 unanswerable questions ask about things a real inbox owner might
plausibly ask but that this corpus does not cover at all: a travel expense
policy, an internal deploy runbook, an on-call rotation, and an office wifi
password. Their `relevant_item_ids` are `[]`.

## What the metrics mean

- **recall@k** — for an answerable question, did at least one relevant
  document id appear anywhere in the top-k ranked results? Averaged over the
  14 answerable questions only (an unanswerable question has no relevant set,
  so recall is undefined for it, not zero — the harness's `recall_at_k`
  correctly returns 0.0 for an empty relevant set, and the report excludes
  those rows from the average by filtering on `answerable`).
- **MRR** (mean reciprocal rank) — averages `1 / rank` of the first relevant
  hit across the answerable questions; 1.0 means the right document was
  always ranked first, not just present somewhere in the top-k.
- **citation validity** — of the answers the system actually gave (didn't
  abstain on), what fraction had every `[n]` marker resolve to a real,
  in-range retrieved passage. This is the grounding check: an answer with an
  invented citation is worse than one with none, because it looks trustworthy
  and isn't.
- **abstention accuracy** — of all 18 questions, what fraction got the right
  behavior: an answer for the 14 answerable ones, a refusal for the 4
  unanswerable ones.
- **threshold sweep** — `sweep_threshold` scores each candidate cosine-score
  cutoff in `THRESHOLD_CANDIDATES` (0.05 to 0.60 in steps of 0.025) by how
  many of the 18 questions it classifies correctly as answerable/unanswerable
  purely from the top retrieval score. Candidates that tie on accuracy are
  broken by margin — the candidate furthest from every observed top score
  wins, which turns "any threshold in a wide gap works" into a specific,
  reproducible maximum-margin choice instead of an arbitrary one (see
  "How the threshold was calibrated" below for why this changed).

## Observed results

Run with `text-embedding-3-small` / `gpt-4o-mini`, `RETRIEVAL_TOP_K=5`,
against the full 18-document corpus (original 15 plus the 3-document hard
slice). Two full runs were made after the hard slice was added — one against
the then-shipped `ABSTAIN_THRESHOLD=0.35` and one after recalibrating to the
new sweep's recommendation (`0.425`); full output for both is in the task
report.

```
== Retrieval (answerable questions only) ==
  recall@5   1.000
  recall@10  1.000
  MRR        1.000

== Grounding ==
  citation validity  1.000
  answers with >=1 citation  14/14

== Abstention ==
  correct refusals   4/4
  correct answers    14/14
  accuracy           1.000
```

**The hard-slice questions did not move any number.** Reported separately,
since that's the subset that actually carries signal about near-neighbor
discrimination: all three hard-slice questions (`q16` linger.ms, `q17` CDN
purge, `q18` EXPLAIN ANALYZE) retrieved their correct document at rank 1
(top score 0.703, 0.554, and 0.585 respectively), so recall@5, recall@10, and
reciprocal rank are all 1.0 on that subset too, and none of the three
plausible-wrong-neighbor documents (`doc_kafka_rebalance`,
`doc_http_caching`, `doc_postgres_indexes`) outranked the correct one for
their question.

That is a real result and it is a weaker one than it looks. Three
near-neighbor pairs is a small sample to draw a general conclusion from, and
`text-embedding-3-small` correctly separating the pairs I happened to write
does not mean it will separate every confusable pair in a real inbox — only
that in these three specific, deliberately-constructed cases, the semantic
content of the question was distinct enough from the wrong neighbor's
content for cosine similarity to prefer the right one. The result says the
hard slice, as authored, did not find a failure; it does not say the system
is immune to near-neighbor confusion in general, and a corpus with many more
confusable pairs, or pairs with subtler differences than "producer vs.
consumer" or "which index" vs. "did it use the index," would be a
meaningfully stronger test. If a future run of this eval, or a larger hard
slice, does produce a miss, that will be the more informative result — a
clean sweep across three added pairs mostly shows the pairs weren't hard
enough yet, not that retrieval is solved.

The original 15-question set's own numbers are unchanged from before the
hard slice was added — see "How the threshold was calibrated" below for the
one thing that did change, which is the recommended threshold value (moving
from three additional high-scoring answerable questions raising the
sweep's margin), not the pass/fail outcome of any original question.

Every headline number above is still 1.000 across all 18 questions, and that
remains **the clearest limitation of this eval**, hard slice included: three
added near-neighbor pairs is still a small, curated set, and "the system
told these three pairs apart" is a much weaker claim than "the system holds
up against near-duplicate content in general." A perfect score here says the
pipeline has no *gross* bugs (chunking, embedding dimension, cosine ranking,
citation validation, and the abstention gate all work end to end) and that
it correctly resolved three specific hard cases — it does not say the system
will hold up against a real inbox with dozens of near-duplicate documents
(several meeting notes about the same project, multiple versions of an API
design doc) where confusable pairs aren't hand-picked to have a clean
semantic distinction.

## How the threshold was calibrated

The shipped default before this task was `ABSTAIN_THRESHOLD=0.25`, chosen
without measurement. Calibration went through two rounds:

**Round 1 (15-question set, before the hard slice).** The sweep found `0.35`
as the accuracy-maximizing cutoff. At the time, the sweep picked the first
candidate to reach the best accuracy score, without a tie-break — and the 11
answerable top scores (0.512–0.738) versus 4 unanswerable top scores
(0.162–0.327) left a clean gap between 0.327 and 0.512 where *every*
candidate threshold scored a perfect 1.0. `0.35` was simply the first such
candidate the sweep happened to reach, not evidence that 0.25 was actually
wrong, and the original writeup said so plainly.

**Round 2 (after the hard slice, with a real tie-break).** That "first
candidate to tie" behavior was a design flaw: shipping a threshold because
it was the first value the loop reached, while documenting that the reason
it won was arbitrary, is closer to cargo-culting than calibration. The sweep
was changed to break accuracy ties by margin — among all candidates scoring
the best accuracy, it now picks the one with the largest minimum distance to
every observed top score, which is the maximum-margin choice, not the first
lucky one. Adding the three hard-slice questions also changed the pool of
observed scores the margin is computed against (14 answerable top scores
now, 0.512–0.738, against the same 4 unanswerable ones, 0.162–0.327). With
the new tie-break, the sweep now reports `0.425` — the candidate closest to
the true midpoint of the 0.327–0.512 gap (0.4195) among the fixed
`THRESHOLD_CANDIDATES` grid (which steps in units of 0.025 and does not
include 0.4195 itself). `ABSTAIN_THRESHOLD` was updated to `0.425` in
`backend/app/config.py`, `.env.example`, and the local `.env`, and the eval
was re-run to confirm: accuracy stayed at 1.0 with no further suggested
change (see the second `make eval` run in the task report).

Two things are worth being explicit about, both true even after this fix.
First, 0.425 is still measured from a corpus where every threshold in a wide
band works — the maximum-margin criterion makes the *choice among ties*
principled, but it can't manufacture a signal the data doesn't contain about
where the true decision boundary should sit. Second, and more fundamentally,
this margin is estimated from **only 4 unanswerable samples**. A margin
computed from four points is a rough sample estimate of where "clearly
unanswerable" ends, not a statistically robust bound — a fifth unanswerable
question with a slightly higher top score than 0.327 could shrink the gap
or eliminate it. 0.425 is a defensible, reproducible, and honestly-derived
value; it is not a guarantee that scores above it are always answerable
questions in a larger or different inbox.

## What this eval does not measure

- **Answer fluency or quality of prose.** Citation validity checks that
  markers resolve to real passages; it says nothing about whether the answer
  is well-written, complete, or non-redundant.
- **Multi-hop questions.** Every golden question, hard slice included, is
  answerable from a single document. Nothing here tests whether the system
  can combine facts from two different items into one answer, which the
  current `Answerer` prompt doesn't explicitly attempt either.
- **Corpora larger than 18 documents**, or corpora with many near-duplicate
  or overlapping documents. The hard slice adds three confusable pairs, not
  dozens — retrieval difficulty, ranking noise, and citation ambiguity all
  scale with corpus size and topical density in ways three pairs cannot
  fully surface. See the "Observed results" caveat above.
- **Latency or cost at scale.** The harness reports per-query timings
  informally via logs but doesn't assert against them; this is a correctness
  eval, not a performance one.
- **Adversarial or genuinely ambiguous questions** — one that's partially
  answerable, or one that could reasonably map to two different documents at
  once. Every golden question here, including the hard-slice ones, was
  written and checked to have exactly one correct document or none; the hard
  slice tests whether a *plausible* wrong answer is avoided, not whether the
  system can handle a question with no single right answer.
- **A statistically robust abstention boundary.** As noted above, the
  calibrated threshold rests on a sample of 4 unanswerable questions. That's
  enough to catch a badly miscalibrated default, not enough to certify a
  precise cutoff.

## Running it

```
make eval
```

Requires `OPENAI_API_KEY` in the repo-root `.env` (real embedding and chat
calls are made; this costs a small amount of money per run). The 8 pure
metric/consistency tests in `backend/tests/test_eval_harness.py` need
neither a key nor network access and run as part of the normal backend test
suite.
