# GeM Mumbai–Palghar Tender Tracker

A public dashboard and scheduled collector for ongoing GeM bids relevant to Mumbai, Palghar and Boisar.

## Strict search scope

The collector searches these buyers one at a time using their full official names, and rejects records unless the buyer is confirmed in public bid/detail/document text:

1. Nuclear Power Corporation of India Limited (NPCIL)
2. Bhabha Atomic Research Centre (BARC)
3. Atomic Energy Education Society (AEES)

No other buyers are retained. Categories are CCTV & surveillance, networking, electrical, fire safety and IT assets. A record must contain evidence for Mumbai, Palghar or Boisar (including Mumbai city/suburb PIN codes and 401xxx Palghar-district PIN codes) in the public bid/detail/document text.

The collector paginates each buyer search through the portal-reported result count. An unexpectedly empty page, page safety-limit breach, network error, portal markup change or access challenge marks the scan incomplete. Incomplete scans preserve the previous tender data rather than publishing a partial result.

## PDF handling

- A PDF link is published only if it is hosted on the official `bidplus.gem.gov.in` domain and the downloaded response begins with the PDF file signature.
- PDF text is extracted with pypdf. Scanned/image-only PDFs are flagged for manual review; OCR is not silently assumed.
- Third-party listing/document URLs are never labelled as verified GeM PDFs.
- Secondary-source candidates may remain visible with a clear pending-verification label until an official scan confirms them.

## Dashboard

The static dashboard reads `data/tenders.json` and `data/status.json`. Enable GitHub Pages from **Settings → Pages → Deploy from a branch → main → /(root)**, or use the included Pages workflow.

## Schedule

Monday–Saturday, hourly from 9:00 AM through 6:00 PM IST. GitHub Actions cron:

```cron
30 3-12 * * 1-6
```

GitHub scheduled runs are best-effort and can be delayed. The runner needs network access to GeM's public BidPlus host. If GeM refuses or blocks the runner's connection, code cannot safely bypass that restriction; the dashboard will show a failed scan and preserve the previous data.

## Run locally

Python 3.11+:

```bash
pip install -r requirements.txt
python scripts/scan_gem.py
python -m unittest discover -s tests -v
```

## Data files

- `data/tenders.json`: deduplicated tender records.
- `data/status.json`: last scan result, timestamp, page counts and warnings.
