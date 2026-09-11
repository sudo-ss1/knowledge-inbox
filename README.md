# knowledge-inbox

Save a note or a link, then ask questions about what you saved. Answers come
back with citations pointing at the passages they came from, and when
nothing you've saved is relevant it says so instead of guessing.

Built as a take-home exercise, in about a day.

## Running it

You need Python 3.12, Node 20 or newer, and an OpenAI key.

```
git clone https://github.com/sudo-ss1/knowledge-inbox.git
cd knowledge-inbox
cp .env.example .env        # put your OPENAI_API_KEY in it
make setup
make dev
```

The UI is on http://localhost:5173, the API on http://localhost:8000.

`make setup` downloads tiktoken's tokenizer vocabulary once (~1.6MB) and
caches it — the only network `make test` needs afterward, since the embedder
and the LLM are fakes there. No API key needed for `make test`. `make eval`
needs one; it calls the real API.

## The API

`POST /ingest` takes `{"type":"note","content":"…"}` or
`{"type":"url","url":"…"}`, returns 202 with a pending item, and doesn't
block on the network. `GET /items` lists what you've saved, newest first,
with a preview instead of the full body; `GET /items/{id}` gives the body.
`POST /query` returns an answer, its sources, and an embed/retrieve/model
latency split. Errors come back as
`{"error":{"code","message","request_id"}}`, and that id is in every log
line for the request.

## How it works

Ingest inserts a `pending` row and hands the id to an in-process queue. Two
workers fetch the page, pull readable text out with trafilatura, chunk and
embed it, then flip the item to `ready` — or `failed`, reason stored and
shown on the row. Queries embed the question, cosine-score it against every
stored chunk, and pass the top five to the model.

## Decisions, and what they cost

**Chunking.** Whole sentences packed into 400-token windows, 60 tokens of
overlap. A saved note is one idea already, so fixed-size splitting would
shred it; an article is long and flat once the markup is gone. Short text
comes out as one untouched chunk; long prose keeps overlap so an answer
doesn't sit on a boundary. Skipped semantic chunking — more machinery than
this needs.

**Vector storage.** Embeddings are float32 blobs in SQLite, scored with a
NumPy dot product. Exact, no index to tune, milliseconds at a few thousand
chunks. Falls over around 100k, since every query reads every embedding.
One narrow interface, though — pgvector is one file away.

**Async.** An `asyncio.Queue`, two workers, not Celery. Two caps concurrent
embedding calls, so twenty pasted URLs slow the queue instead of triggering
429s. Queued work survives a restart; mid-flight work does not. A real
broker fixes both, and I'd add one before this had more than one user.

**Abstaining.** Below a score threshold, the model never gets called. An
answer citing nothing valid is discarded and replaced with "I don't have
anything saved that answers that." Any `[n]` the model invents is dropped
first. This refuses some answerable questions. Worth it — a confident wrong
answer costs more than an admission.

**No state library.** App state is one list of items plus one hook for the
ask panel. Redux would be ceremony here.

The threshold isn't a guess, but don't oversell it. `eval/` runs an
18-document corpus and 18 questions — 14 answerable, 4 not — against real
OpenAI calls. Recall@5 and MRR land at 1.000 for dense retrieval, and
identically 1.000 for a plain BM25 baseline. The headline: at 18 documents
with mostly distinct vocabulary, embeddings buy nothing measurable over
string matching. Grounding, checked against raw model output, came back 15
citation markers emitted, zero invented. `ABSTAIN_THRESHOLD` ships at 0.34,
the max-margin point in a gap only 0.0224 wide from 4 unanswerable samples —
too thin to call solid calibration. Details in
[`eval/README.md`](eval/README.md).

## What I left out

No auth, no Docker, no re-ranking. No hybrid BM25 in the real query path,
only in the eval as a baseline — next time I'd wire it into the actual
retriever from day one, since it already matches dense retrieval here and
hybrid would be nearly free to add. No streaming answers, no dedup on saving
a URL twice, no headless browser — a JavaScript-rendered page fails with a
readable message instead of saving an empty item. The SSRF guard resolves
the hostname to check it's public, then `httpx` resolves it again on
connect — a hostile authoritative server could answer differently between
the two lookups, and closing that TOCTOU gap properly is out of scope here.
The API's keyset pagination on `/items` is implemented and tested, but the
frontend only ever fetches the first page — there's no "load more" in the UI.

## If this went to production

At scale the first things to break are the O(N) query scan, the single
SQLite writer, and the in-process queue. In that order.

So Postgres with pgvector first — that clears the first two at once, and
since retrieval sits behind one narrow interface it's a file, not a rewrite.
Then a real broker with workers in their own process, so ingestion survives a
deploy and stops competing with request handling. Those two are most of the
scaling story.

After that it's the unglamorous list. Per-user rows and auth, because right
now every query reads every chunk in the database. Dedup on a content hash, so
saving the same URL twice doesn't pay to embed it twice. A cache on query
embeddings, since people re-ask the same question. Rate limits on ingest.
Hybrid BM25 in the query path, which the eval already argues for. Logging is
the one thing I'd leave alone — the request id already threads through every
line, so wiring it to traces is plumbing, not redesign.
