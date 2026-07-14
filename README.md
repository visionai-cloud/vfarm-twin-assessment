# vFarm Event Ingestion + Summary

A minimal, runnable slice of the "engine" behind the digital vertical farm:
ingest farm events from two sources, normalize them into one **Farm Events**
store with a clean separation of *raw / normalized / derived*, and expose a
**"Last 24 Hours in the Farm"** summary shaped for an AI agent to narrate.

It runs with **zero setup** (SQLite by default) and is **Postgres-ready** for the
real deployment — same code, one env var.

---

## TL;DR — run it

```bash
cd vfarm-events
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# API on http://127.0.0.1:8000
uvicorn app.main:app --reload

# in another shell — Source B: polls the sheet on a schedule
python poller.py

# run the tests (30, all green)
pytest -q
```

Then:

```bash
# Source A — a farm event pushed to the webhook (auth required)
curl -X POST localhost:8000/ingest/webhook \
  -H 'X-VFarm-Token: dev-secret-change-me' -H 'Content-Type: application/json' \
  -d '{"type":"sensor","location":"Pod B","notes":"Nutrient pump blocked","source_event_id":"evt-1"}'

# Source B — pull the builder-updates sheet now
curl -X POST localhost:8000/ingest/sheet

# The structured summary an AI would narrate
curl localhost:8000/summary/last-24h

# The same summary, narrated into prose (LLM if OPENAI_API_KEY set, else template)
curl localhost:8000/summary/last-24h/narrate
```

---

## Design principles (the part that matters)

**1. Three layers, never collapsed.** Every event row physically separates:

| Layer | Column(s) | Who writes it | Why separate |
|---|---|---|---|
| **Raw** | `raw_payload` (JSONB) | the source, verbatim | audit + replay; we can re-derive everything if our logic changes |
| **Normalized** | `event_time`, `event_type`, `location`, `notes` | `normalize.py` | clean, indexed, queryable facts |
| **Derived** | `tags` (`[BLOCKER]`, `[SUCCESS]`, …) | `tagging.py` | *our interpretation* — cheap to recompute, must never be confused with facts |

If our tagging rules change tomorrow, we replay `raw_payload` → new `tags`. The
raw truth is never lost, and derived opinions never contaminate it.

**2. Event time ≠ system time.** `event_time` (when it happened in the farm)
is stored separately from `received_at` (when we ingested it). Builder sheets
and delayed sensor streams arrive late; the 24h window is computed on
`event_time` so backfilled data lands in the right window. *(This is the same
lesson industrial twins learn the hard way — see "Prior art" below.)*

**3. Append-only, no silent overwrites.** Events are immutable. Re-delivering
the same event (webhook retry, re-polling the same sheet row) is de-duplicated
on a `dedup_hash`, not UPSERT-ed. A re-delivery with tampered fields returns
`{"stored": 0, "duplicates": 1}` — the original is never mutated. This is the
"safe" requirement, enforced by a `UNIQUE` constraint, not by hope.

**4. One funnel, many sources.** Both sources converge on `ingest_events()`.
Adding Source C (MQTT, Otter transcript, Discord webhook) = write a small
adapter that produces `raw` dicts and call the same funnel. Nothing downstream
changes.

**5. Extend without migrating.** New event type → add one line to a synonym
map. New tag → add one rule to `TAG_RULES`. Neither touches the schema.

---

## Schema — the unified Farm Events store

One table, `farm_events`:

| Column | Type (PG / SQLite) | Layer | Notes |
|---|---|---|---|
| `id` | `uuid` / text | — | primary key |
| `source` | `varchar(32)` | raw | `"webhook"` \| `"sheet"` \| … |
| `source_event_id` | `varchar(128)` null | raw | the source's own id, if any |
| `dedup_hash` | `varchar(64)` **UNIQUE** | raw | idempotency key (see below) |
| `event_time` | `timestamptz` | normalized | **when it happened** (indexed) |
| `received_at` | `timestamptz` | normalized | **when we ingested** it |
| `event_type` | `varchar(64)` | normalized | canonical type (indexed w/ time) |
| `location` | `varchar(128)` | normalized | slug, e.g. `pod-a-rack-3` (indexed w/ time) |
| `notes` | `text` | normalized | free text |
| `tags` | `text[]` / JSON | **derived** | `["BLOCKER","ALERT"]` |
| `raw_payload` | `jsonb` / JSON | **raw** | exactly what arrived |
| `normalized` | `jsonb` / JSON | normalized | structured copy of the normalized view |
| `schema_version` | `int` | — | bump when the normalization contract changes |

**Indexes:** `event_time`; `(event_type, event_time)`; `(location, event_time)`
— the three axes the summary groups by. `UNIQUE(dedup_hash)` enforces idempotency.

**`dedup_hash`** = `sha256(source + source_event_id)` when the source supplies an
id, else `sha256(source + canonical(raw_payload))`. So a retried webhook or a
re-polled spreadsheet row collapses to one row; a genuinely new event doesn't.

---

## Stack choice

| Concern | Choice | Why |
|---|---|---|
| API | **FastAPI** (Python 3.9+) | webhook + summary in a few typed handlers; async-ready; the client suggested it |
| Store | **Postgres** (target) / **SQLite** (local) | JSONB for raw, `text[]` for tags, real indexes; SQLite variant means reviewers run it with zero setup |
| ORM | **SQLAlchemy 2.0** | one model, portable across both engines via column variants |
| Validation | **Pydantic v2** | request/response contracts; `extra="allow"` so unknown webhook fields are preserved, not rejected |
| Source B poller | plain loop / cron | no scheduler dependency; in prod this is a cron or **Vercel Cron** hitting `POST /ingest/sheet` |

Deliberately boring and swappable. Nothing here is load-bearing on a specific
vendor.

---

## Ingestion flow

```
 Source A (webhook)                 Source B (sheet / CSV, polled)
 sensor alert / builder update      builders type into a Google Sheet
        │  POST /ingest/webhook            │  poller.py  →  POST /ingest/sheet
        │  (X-VFarm-Token auth)            │  fetch_rows() → parse_csv()
        ▼                                  ▼
   raw dict                           list[raw dict]
        └───────────────┬──────────────────┘
                        ▼
                 ingest_events()            ◀── the single funnel
                        │
            normalize_event()   ── raw → {event_time, type, location, notes, dedup_hash}
                        │
              derive_tags()     ── notes/type → [BLOCKER|SUCCESS|EXPERIMENT|ALERT]
                        │
            dedup on dedup_hash ── batch-internal + against stored rows
                        │
                 append (INSERT)          ◀── immutable, no UPSERT
                        ▼
                  farm_events
                        │
              GET /summary/last-24h  ── group by type/location, bucket blockers vs successes
                        ▼
            AI-narratable summary JSON
```

**Pseudo-code of the shared funnel** (real code in `app/ingest.py`):

```python
def ingest_events(session, source, raw_payloads):
    now = utcnow()
    for raw in raw_payloads:
        norm  = normalize_event(source, raw, now=now)   # pure
        tags  = derive_tags(norm.type, norm.notes)       # pure
        event = FarmEvent(**norm, tags=tags, raw_payload=raw, received_at=now)
        if event.dedup_hash not in already_seen:         # batch + DB check
            session.add(event)                           # append only
    session.commit()
    return {"stored": n, "duplicates": d, "ids": [...]}
```

---

## The "Last 24 Hours in the Farm" summary

`GET /summary/last-24h` returns a shape built for narration — counts for the
skeleton, then the actual events an agent would quote:

```jsonc
{
  "window_start": "...", "window_end": "...",
  "total_events": 5,
  "by_type":     { "sensor_alert": 1, "builder_update": 3, "experiment": 1 },
  "by_location": { "pod-b": 2, "pod-a-rack-3": 1, "pod-c": 1, "pod-a-rack-1": 1 },
  "counts":      { "blockers": 2, "successes": 2, "experiments": 1 },
  "blockers":    [ { "location": "pod-b", "notes": "Nutrient pump blocked, waiting on part", "tags": ["ALERT","BLOCKER"] }, ... ],
  "successes":   [ ... ],
  "experiments": [ ... ]
}
```

An agent turns that into: *"In the last 24h the farm logged 5 events across 4
pods. Two blockers — most urgent, a nutrient-pump failure in Pod B. Two
successes including a basil harvest in Pod A. One experiment is running in Pod C
(16h vs 18h light cycle)."* The endpoint does the grouping; the LLM does the prose.

## Where the AI lives (and where it deliberately doesn't)

The ingestion / normalization / summary path is **100% deterministic** — no LLM,
no network, fully unit-tested. AI hallucination and per-event cost have no place
in the facts layer. The AI sits at exactly one edge:

`GET /summary/last-24h/narrate` takes the *already-computed* summary and turns it
into an operator briefing. The LLM is a **pure consumer** of deterministic data —
it can only rephrase facts we hand it, never touch the store.

```jsonc
{
  "narration": "In the last 24 hours the farm logged 4 events across 4 locations. 1 blocker needs attention — most notably pod-b: Nutrient pump blocked... 2 successes logged. 1 experiment running, including in pod-c.",
  "generated_by": "openai",       // or "fallback"
  "model": "gpt-5.4-mini",
  "summary": { ... }               // the structured data it was built from
}
```

- **`OPENAI_API_KEY` set** → OpenAI narrates (`app/narrate.py`, model via `OPENAI_MODEL`).
- **Unset / call fails** → a deterministic **template** produces the same shape.
  So the repo runs offline, at zero cost, and tests never hit the network.

Provider is swappable — `narrate()` is the only function that does I/O; the prompt
builder and fallback are pure. Smarter (LLM-based) *tagging* is a documented next
step, intentionally left out to keep the derived layer cheap and re-derivable.

---

## How to extend

- **New source** (MQTT, Otter transcript): adapter → `raw` dicts → `ingest_events(session, "otter", rows)`. Done.
- **New event type**: add a synonym to `_TYPE_SYNONYMS` in `normalize.py`.
- **New tag**: add a rule to `TAG_RULES` in `tagging.py`; re-derive over `raw_payload` to backfill.
- **Real Google Sheets auth**: swap `fetch_rows()` for the Sheets API; the parser is unchanged.

---

## Testing

30 tests, matching the surface:

- **Unit** (pure logic): `test_normalize.py`, `test_tagging.py`, `test_summary.py`, `test_sheet.py`, `test_narrate.py` — types, slugs, timestamp parsing (ISO/epoch/garbage), dedup-hash stability, tag rules, summary bucketing, narration prompt + template fallback.
- **Integration** (routes): `test_api.py` — webhook **auth-denied** (no token / wrong token) + **auth-allowed** + happy path, **idempotent re-delivery** (no silent overwrite), sheet ingest idempotency, summary buckets, and the narrate endpoint's offline fallback.

```bash
pytest -q
```
→ `30 passed`

---

## Future-proofing for the "farm twin"

This is a deliberate v0 of a twin's memory, not a toy:

- **`raw_payload` retained forever** → the twin can re-derive new signals from old events when its understanding improves.
- **`event_time` vs `received_at`** → time-travel queries ("what did the farm look like *as of* last Tuesday?") stay correct even with late data. This generalizes to snapshotting/temporal storage later.
- **Append-only + `dedup_hash`** → an immutable event log is exactly what a learning twin needs to replay history deterministically.
- **`tags` as a separate, recomputable layer** → today keyword rules; tomorrow an LLM classifier writing richer derived signals — without ever touching the raw facts.

### Prior art / disclosure

I've built the production-scale version of this pattern (sensor connectors →
time-series telemetry with event-time vs system-time → digital twin + agent
memory + temporal "as-of" queries) on a real digital-twin platform. The
architecture choices here — raw/normalized/derived separation, event-time
handling, connector-as-a-funnel, append-only memory — come from that
experience, reduced to the smallest thing that stands on its own for the vFarm.
No proprietary code is used or included; this repo is written from scratch.
```
