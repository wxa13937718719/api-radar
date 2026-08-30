# API Radar

API Radar is a Windows-local system for monitoring AI API providers, normalizing
model identities and prices, retaining historical snapshots, and producing
explainable recommendations. Phase A is the foundation and intentionally does
not invent provider data.

## Phase A layout

```text
api_radar/
  app.py                 FastAPI application factory and health endpoint
  config.py              environment-backed settings
  db.py                  SQLAlchemy engine/session helpers
  models.py              durable schema and UTC timestamps
  providers/base.py      adapter interface and normalized DTOs
  providers/registry.py  isolated adapter registration
scripts/scan.py          automation-safe scan entry point
scripts/report.py        automation-safe report entry point
automation/openclaw/     future OpenClaw boundary
tests/                   pytest foundation
```

## Core design

The database keeps provider-native model names alongside a nullable canonical
model identity. Ambiguous aliases remain unmapped. Every price is a snapshot and
retains original currency/price, normalized values, exchange-rate metadata, source
URL, capture time, and safe raw data. Decimal/Numeric columns are used for money;
all timestamps are stored as UTC.

The main entities are `Provider`, `Model`, `ProviderModel`, `ModelAlias`,
`PriceSnapshot`, `ModelPrice`, `Promotion`, `Source`, `UserAsset`,
`Recommendation`, `ScanRun`, and `ScanResult`. `PriceSnapshot` is immutable
history; `ModelPrice` is the latest price board for fast cross-platform
comparison. `UserAsset` stores only local account state, package and available
models—never an API key.

## Five highest-risk areas

1. Provider pages and APIs change frequently; adapters need diagnostics and fixture tests.
2. Model identity is semantic, so uncertain aliases must not be auto-merged.
3. Currency conversion and token units can silently create incorrect comparisons.
4. Partial failures must be isolated so one provider never aborts a scan run.
5. Promotions and community intelligence require provenance and confidence, not guesses.

## Run locally

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn api_radar.app:app --reload
python scripts/scan.py --dry-run
pytest
```

No API keys or passwords are required. Phase B implements OpenRouter through its
public model catalog. Run a real scan with `python scripts/scan.py --provider openrouter`.
The adapter keeps the original USD/token prices and writes converted CNY/1M-token
snapshots using a separately captured USD/CNY exchange rate.

SiliconFlow is supported through its public pricing page (its model API
requires a token). Run `python scripts/scan.py --provider siliconflow` to scan
published input prices; unpublished output/cache prices remain null. Explainable
recommendations are available through `python scripts/report.py --profile low_cost`.
Profiles include `daily_chat`, `coding`, `writing`, `long_context`, `reasoning`,
`vision`, and `local_offline`; each result retains score dimensions and a
human-readable reason.

The FastAPI API exposes `/providers`, `/scans`, `/prices/history`,
`/prices/changes`, `/prices/compare/{canonical_model_id}`, `/model-prices`,
`/decision/today`, `/decision/recommendations/{profile}`, `/assets`, and
`/recommendations/{profile}`. `POST /scans?provider=all` starts a background
scan; pass a registered provider ID to scan just that provider.
Price comparison intentionally returns only models with an explicit canonical
mapping, so similarly named provider models are never silently merged. Use
`python scripts/scan.py --provider all` to scan every registered provider with
per-provider failure isolation.

## Dashboard

The React + TypeScript dashboard lives in `dashboard/`. Start the API and UI in
two terminals:

```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn api_radar.app:app --reload
cd dashboard
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The dashboard is a decision centre: it ranks the
top five models for seven task types, explains the AI Value Score (ability 40%,
price 30%, speed 15%, availability 15%), prefers configured assets, and shows
price board, changes, offers, risks and source capture time. The account form
never accepts or stores an API key. GitHub, Linux.do and Reddit are collected as
leads only; public provider pages remain the source for price facts and scores.
`npm run build` creates the production bundle in `dashboard/dist`.
When the API uses a non-default port, start the dashboard with
`$env:API_RADAR_API_URL='http://127.0.0.1:8001'; npm run dev`.

## Open the dashboard anytime

Install a desktop launcher once:

```powershell
cd "D:\AI\API Radar"
powershell -ExecutionPolicy Bypass -File .\scripts\install_launcher.ps1 -StartNow
```

It creates **API Radar 驾驶舱** on the desktop and registers the global hotkey
`Ctrl + Alt + R`. Both open a modern Edge app window. The launcher starts the
local API (`:8000`) and dashboard (`:5173`) only when they are not already
running; its logs are stored under `data/`. To change the hotkey, run the same
installer with `-Hotkey 'CTRL+ALT+A'`.

To start the API and dashboard automatically after Windows sign-in without a
terminal window, install the interactive background task once:

```powershell
# 请在“以管理员身份运行”的 PowerShell 中执行
powershell -ExecutionPolicy Bypass -File .\scripts\install_background.ps1
```

开机任务会先检查是否接通交流电：未接电时不会启动 API、Dashboard，也不会弹出窗口；接通电源后保持正常启动。手动调试时可使用 `-IgnorePowerCheck` 跳过检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\open_radar.ps1 -IgnorePowerCheck
```

It waits 20 seconds for the network, starts missing local services invisibly,
and opens the dashboard. The legacy daily briefing window has been removed; all
scheduled and on-demand work now stays inside the dashboard and local API.

Model identity confirmation is deliberately explicit through
`POST /models/{provider_id}/{provider_model_id}/identity`; no ambiguous alias is
automatically merged. Official intelligence capture stores sanitized source text
in `Source`; promotion records require a supplied public source and confidence.

## Daily briefing and chat

Every generated report now includes a `briefing` paragraph. The dashboard shows
the same briefing on the overview page and provides a chat box backed by
`POST /assistant/chat`. With the default configuration this assistant uses only
local deterministic rules and captured facts.

An optional OpenAI-compatible model can rewrite the briefing and answer follow-up
questions. This works with Ollama, LM Studio, vLLM, or a compatible cloud gateway:

```env
API_RADAR_LLM_ENABLED=true
API_RADAR_LLM_BASE_URL=http://127.0.0.1:11434/v1
API_RADAR_LLM_API_KEY=
API_RADAR_LLM_MODEL=llama3.2
```

For the local Qwen service detected on this computer, `.env` is configured to
use `qwen/qwen3.5-9b` at `http://127.0.0.1:1234/v1`. Its thinking mode is
disabled for this concise advice workflow; that prevents a short briefing from
being consumed entirely by hidden reasoning tokens. Keep
`API_RADAR_LLM_DISABLE_REASONING=false` for standard cloud APIs.

The model receives only normalized recommendations and public price-change facts.
If it is unavailable or returns an invalid response, API Radar automatically falls
back to the deterministic rules briefing. A small local model is sufficient for
rewriting and conversational follow-up; it is not used to calculate prices or
decide factual model identity.

The dashboard background task is the only supported Windows startup path. The
dashboard chat learns only explicit local preferences,
such as "优先低成本" or "更看重工具调用". These are stored in SQLite and used as
recommendation weights; they never change provider facts or model identity.
