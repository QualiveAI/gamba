# Root Vercel API deployment

`api/index.py` imports the existing FastAPI app from `backend/app`.
`api/cron/auto_pause.py` is a guarded Vercel Cron endpoint. The root `vercel.json`
registers it every ten minutes. Set `CRON_SECRET` in Vercel; never commit it.

If Vercel cannot trace the `backend/` package in the first build, use the prepared
Hax/Woiden systemd fallback in `deploy/hosting/systemd/` instead of weakening imports
or copying secrets into the repository.
