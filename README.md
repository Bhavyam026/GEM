# GeM Mumbai–Palghar Tender Tracker

A public dashboard and scheduled collector for **ongoing GeM bids** relevant to Mumbai and Palghar.

## Scope
- Geography: Mumbai and Palghar only. A result is retained only when its visible bid row/detail contains Mumbai or Palghar.
- Categories: CCTV & surveillance, networking, electrical, fire safety, and IT assets.
- Priority buyer labels: NPCIL, BARC, and AEES. Other matching buyers are included too.
- Pages: collector follows the portal's visible Next control, with a safety cap.
- Schedule: Monday–Saturday, every hour from 9:00 AM to 6:00 PM IST (GitHub Actions UTC cron).

## Dashboard
The static dashboard reads `data/tenders.json` and `data/status.json`. Enable GitHub Pages from **Settings → Pages → Deploy from a branch → main → /(root)**, or use the included Pages workflow.

## Collector
The GitHub Actions workflow installs Playwright Chromium, opens the public GeM Advanced Search page, reads visible result rows, follows pagination, filters the rows, and commits updated JSON.

### Important operational limits
- GeM's Advanced Search currently exposes ongoing bids; this is not an archive of all historical tenders.
- The portal can change its markup, become unavailable, rate-limit requests, or present CAPTCHA/login controls. The collector does **not** bypass CAPTCHA, OTP, login, or other access controls. A challenge is recorded as a failed scan for manual review.
- A first successful workflow run is required to validate the live portal's current result-page structure. Do not represent the dashboard as fully validated until that run completes and its collected rows are checked.
- Matching is based on information visible in the public result rows. If GeM hides the delivery/consignee location until opening a bid detail, that record may need a later detail-page adapter.
- GitHub Actions scheduled runs are best-effort and may be delayed by GitHub.

## Run locally
Python 3.11+
```bash
pip install -r requirements.txt
playwright install chromium
python scripts/scan_gem.py
```

## Schedule
`30 3-12 * * 1-6` UTC = 9:00 AM–6:00 PM IST, Monday–Saturday.

## Data
- `data/tenders.json`: deduplicated current matches keyed by GeM bid number (or a stable URL/title fallback).
- `data/status.json`: last scan status, timestamp, page count, and warnings.
