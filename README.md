# web_experiment

Standalone BYO-wallet web experiment for Polymarket trading.

## What It Includes

- FastAPI backend with SIWE-style auth:
  - `POST /api/auth/nonce`
  - `POST /api/auth/verify`
  - `GET /api/me`
  - `GET /api/search`
  - `POST /api/order/limit`
  - `POST /api/tp/arm`
  - `GET /api/tp/status`
- Static UI served by backend at `/`
- Browser wallet signing for:
  - SIWE message
  - CLOB auth typed-data
  - Entry LIMIT order typed-data
  - TP SELL typed-data orders
- In-memory sessions + TP arm state (MVP)

## Project Layout

```text
web_experiment/
  backend/
    main.py
    auth.py
    store.py
    resolver.py
    clob_session.py
    tp_engine.py
    integrations/
      dome_client.py
      market_fallback.py
    polymarket/
      clob_trading.py
  ui/
    index.html
    app.js
    styles.css
  requirements.txt
```

## Required Environment Variables

- `WEB_EXPERIMENT=1`
- `DOME_API_KEY=...`
- Builder credentials (pick one mode):
  - Local builder key mode:
    - `BUILDER_API_KEY=...`
    - `BUILDER_API_SECRET=...` (or `BUILDER_SECRET`)
    - `BUILDER_API_PASSPHRASE=...` (or `BUILDER_PASS_PHRASE`)
  - Remote builder signing mode:
    - `BUILDER_SIGNING_URL=...`

Optional:

- `WEB_EXPERIMENT_CLOB_HOST=https://clob.polymarket.com`
- `WEB_EXPERIMENT_CHAIN_ID=137`
- `WEB_EXPERIMENT_SESSION_TTL_SECONDS=43200`
- `WEB_EXPERIMENT_NONCE_TTL_SECONDS=300`
- `WEB_EXPERIMENT_TP_POLL_SECONDS=2`
- `WEB_EXPERIMENT_TP_MAX_MINUTES=30`
- `DOME_BASE_URL=https://api.domeapi.io/v1`
- `WEB_EXPERIMENT_FORCE_SIGNATURE_TYPE=0|1|2` (debug override)
- `WEB_EXPERIMENT_FORCE_TRADING_ADDRESS=0x...` (debug override)

Notes:

- Server never stores user private keys.
- `MASTER_KEY` is not required for this flow.
- `wallet_manager.py` is not used.

## Install

```bash
pip install -r web_experiment/requirements.txt
```

## Run Backend + UI

From the parent directory that contains the `web_experiment/` package:

```bash
WEB_EXPERIMENT=1 uvicorn web_experiment.backend.main:app --reload --port 8080
```

PowerShell:

```powershell
$env:WEB_EXPERIMENT='1'
uvicorn web_experiment.backend.main:app --reload --port 8080
```

Open:

- `http://localhost:8080/`

## Manual Test Flow

1. Connect wallet and sign auth prompts.
2. Search team/project via Dome.
3. Select a market and place BUY limit order.
4. Arm TP (single or ladder).
5. Refresh TP status and watch TP placement after entry fills.
