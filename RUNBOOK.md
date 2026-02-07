# Hunky Bot Runbook

## 1. First setup
1. Copy `.env.example` to `.env` and fill required values.
2. Generate Google OAuth token with `python3 setup_token.py`.
3. Start services:
   - Python API: `python3 app.py`
   - WA engine: `node wa-engine/index.js`
   - Or all-in-one: `npm run start:all`

## 2. Re-pair WhatsApp
1. Delete local WA session folder `auth_session/`.
2. Start WA engine and use pairing code from logs.
3. Confirm `/health` endpoint returns healthy.

## 3. Credential rotation (mandatory if repository ever exposed)
1. Rotate `BLACKBOX_API_KEY` in Blackbox dashboard.
2. Rotate Google OAuth app secret (`client_secret.json`) and regenerate `token.json`.
3. Rotate/refresh `credentials.json` (service account key) if used.
4. Remove all old credentials from local machine and CI secrets.

## 4. Incident recovery
1. Check Python health: `curl http://127.0.0.1:5000/health`.
2. Check WA health: `curl http://127.0.0.1:3000/health`.
3. If reminder is stuck, restart both services.
4. If AI request times out, verify `BLACKBOX_API_URL`, API key, and outbound network.

## 5. Git history cleanup (manual, high impact)
1. Coordinate maintenance window with all collaborators.
2. Run `./scripts/rewrite_history.sh`.
3. Verify history no longer contains sensitive files.
4. Force push rewritten history and notify team to re-clone.
