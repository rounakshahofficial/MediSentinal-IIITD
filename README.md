# MediSentinel-H

MediSentinel is a human-in-the-loop medicine-price compliance intelligence prototype for
India. It scans permitted **online** pharmacy listings for one medicine family
(Atorvastatin), deterministically matches each listing to an NPPA ceiling-price reference,
calculates a potential discrepancy only when required fields are unambiguous, and builds
an auditable evidence dossier for a reviewer.

## Prototype scope

- Sites: Tata 1mg, PharmEasy, and Netmeds
- Medicine family: Atorvastatin
- No offline pharmacies and no map
- Scanner: TinyFish behind `ScannerClient`, or deterministic cached JSON through
  `MockScanner`
- Human actions: confirm for review, dismiss, or request more evidence
- Advisory triage only; outputs require human verification

> **Reference warning:** `backend/data/reference_prices.csv` contains six sample,
> unverified rows. Replace them with values checked against official NPPA Gazette S.O.
> orders before any formal review use.

## Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite
- Matching: deterministic parsing plus RapidFuzz typo gating
- PDF: WeasyPrint
- Frontend: React, Vite, TypeScript, Tailwind, shadcn-style components, TanStack Query,
  Recharts

## Quick setup with SQLite and cached demo scans

Prerequisites: Python 3.11 and Node.js `^20.19` or `>=22.12`.

### 1. Backend

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

For a local SQLite demo, set this line in `backend/.env`:

```dotenv
DATABASE_URL=sqlite:///./medisentinel.db
SCANNER_MODE=mock
CACHED_RUN_FALLBACK=true
```

Initialize data and start FastAPI:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_references.py
.venv/bin/python scripts/demo_scanner.py
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API documentation: `http://localhost:8000/docs`

### 2. Frontend

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/storage` to port 8000.

## PostgreSQL setup

Start a local PostgreSQL container:

```bash
docker run --name medisentinel-postgres \
  -e POSTGRES_USER=medisentinel \
  -e POSTGRES_PASSWORD=medisentinel_dev \
  -e POSTGRES_DB=medisentinel \
  -p 5432:5432 \
  -d postgres:16
```

Use the default URL from `.env.example`:

```dotenv
DATABASE_URL=postgresql+psycopg://medisentinel:medisentinel_dev@localhost:5432/medisentinel
```

Then run:

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_references.py
```

## Scanner modes and cached-run fallback

Available scanner modes:

```dotenv
SCANNER_MODE=mock            # deterministic cached JSON
SCANNER_MODE=tinyfish_rest   # TinyFish SSE endpoint
SCANNER_MODE=tinyfish_sdk    # TinyFish Python SDK
```

TinyFish credentials belong only in `backend/.env`:

```dotenv
TINYFISH_API_KEY=your_key_here
```

Enable fallback globally:

```dotenv
CACHED_RUN_FALLBACK=true
```

Or choose it per request:

```bash
curl -sS -X POST http://localhost:8000/scans \
  -H 'Content-Type: application/json' \
  -d '{
    "medicine_family": "atorvastatin",
    "scanner_mode": "tinyfish_rest",
    "use_cached_fallback": true
  }'
```

If live scanner initialization fails, or individual pharmacy runs fail, only affected sites
are retried through `MockScanner`. The response explicitly reports:

```json
{
  "requested_scanner_mode": "tinyfish_rest",
  "scanner_mode": "tinyfish_rest+mock_fallback",
  "fallback_used": true,
  "fallback_sites": ["1mg", "pharmeasy", "netmeds"]
}
```

The Scan page provides the same switch and displays a visible cached-data disclosure.
Cached output must never be presented as current live pharmacy data.

## Main API routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/scans` | Run scan → parse → match → calculate → case pipeline |
| `GET` | `/scans/logs` | Scanner attempts, errors, and latency |
| `GET` | `/listings` | Raw listings with parse/match audit |
| `GET` | `/cases` | Filtered and sorted human-review queue |
| `GET` | `/cases/{id}` | Full evidence dossier |
| `POST` | `/cases/{id}/review` | Record reviewer action |
| `GET` | `/cases/{id}/dossier.pdf` | Download dossier PDF |
| `GET` | `/stats` | Overview metrics and recurrence groups |

The frontend uses equivalent `/api/...` aliases.

## WeasyPrint PDF requirements

The Python dependency also needs native Pango libraries. On Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
```

On macOS:

```bash
brew install pango
```

See `backend/WEASYPRINT.md` for details. Lean preview environments without Pango use a
field-complete `fpdf2` fallback so the download endpoint remains operational; production
images should install Pango for the primary WeasyPrint HTML/CSS layout.

## 90-second walkthrough

The timed spoken script, click sequence, and live-scan recovery cue are in:

```text
docs/demo-90-seconds.md
```

## Measuring against your manual ground truth

Start from the documented example:

```bash
cp backend/data/manual_ground_truth.example.csv /path/to/my_ground_truth.csv
```

Required columns:

| Column | Meaning |
|---|---|
| `site` | `1mg`, `pharmeasy`, or `netmeds` |
| `url` | Manually inspected listing URL |
| `observed_at` | ISO-8601 observation timestamp; required when the same URL appears more than once |
| `expected_ingredient` | Human-labelled ingredient |
| `expected_strength` | Human-labelled normalized strength |
| `expected_dosage_form` | Human-labelled normalized form |
| `expected_units_in_pack` | Human-labelled integer count; blank when truly unclear |
| `expected_match_status` | `matched`, `uncertain`, or `no_match` |
| `expected_flag` | `true` when manual per-unit review finds an above-tolerance potential discrepancy |

Run the comparison against `DATABASE_URL` from `backend/.env`:

```bash
cd backend
.venv/bin/python scripts/measure_ground_truth.py \
  /path/to/my_ground_truth.csv \
  --json-output measurement-report.json
```

Optional quality gates return exit code 2 when a metric falls below its threshold:

```bash
.venv/bin/python scripts/measure_ground_truth.py \
  /path/to/my_ground_truth.csv \
  --min-extraction-rate 0.90 \
  --min-match-accuracy 0.90 \
  --min-flag-precision 0.80
```

Metric definitions:

- **Extraction rate:** manually labelled observations found by site + URL + optional
  timestamp, divided by all manual rows.
- **Match accuracy:** among extracted rows, correct expected status; a `matched` row must
  also agree on ingredient, strength, dosage form, and units in pack.
- **Flag precision:** true positive price flags divided by all system positive price flags.
  Positive system listings absent from the manual CSV count as false positives.

`manual_ground_truth.example.csv` mirrors the cached fixtures and is a smoke-test example,
not an independent benchmark. Replace it with your own manually inspected labels when
reporting product performance.

## Tests

Backend:

```bash
cd backend
.venv/bin/pytest -q
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

## Repository layout

```text
backend/app/                 FastAPI, models, deterministic pipeline, PDF rendering
backend/data/                sample references, cached scans, ground-truth example
backend/scripts/             seed, demo, and measurement commands
backend/tests/               parser, matcher, calculator, scanner, API, PDF, metrics tests
frontend/src/pages/          Overview, Scan, Match Check, Queue, Dossier
storage/evidence/            captured listing screenshots
docs/demo-90-seconds.md      timed hackathon walkthrough
```
