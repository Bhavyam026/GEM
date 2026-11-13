#!/usr/bin/env python3
"""Public GeM collector restricted to NPCIL, BARC and AEES.

Uses only public BidPlus pages. It does not bypass CAPTCHA, login, OTP,
rate limits or other access controls. An incomplete scan never replaces data.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar
from zoneinfo import ZoneInfo

try:
    from scripts.pdf_extract import extract_detail_documents
except ModuleNotFoundError:
    from pdf_extract import extract_detail_documents

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASE = "https://bidplus.gem.gov.in"
ALL_BIDS = BASE + "/all-bids"
SEARCH_API = BASE + "/all-bids-data"
IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
REQUEST_DELAY = 0.75
MAX_PAGES_PER_BUYER = 500

BUYERS = {
    "NPCIL": {
        "name": "Nuclear Power Corporation of India Limited",
        "aliases": ("Nuclear Power Corporation of India Limited", "NPCIL"),
    },
    "BARC": {
        "name": "Bhabha Atomic Research Centre",
        "aliases": ("Bhabha Atomic Research Centre", "BARC"),
    },
    "AEES": {
        "name": "Atomic Energy Education Society",
        "aliases": ("Atomic Energy Education Society", "AEES"),
    },
}

SEARCH_TERMS = {
    "CCTV & Surveillance": ("CCTV", "NVR", "DVR", "IP Camera", "Video Surveillance", "Surveillance Camera"),
    "Networking": ("Networking", "LAN Switch", "Router", "Optical Fiber", "Network Switch", "Firewall"),
    "Electrical": ("Electrical Panel", "PLC SCADA", "Electrical Cable", "Earthing", "Electrical Wiring", "Lighting Fixture"),
    "Fire Safety": ("Fire Alarm", "Fire Safety", "Fire Extinguisher", "Smoke Detector", "Fire Detection"),
    "IT Assets": ("Desktop Computer", "Laptop", "Computer Monitor", "Printer", "IT Equipment", "Server"),
}


def now_ist():
    return datetime.now(IST)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def normalize_bid_number(value):
    return re.sub(r"\s+", "", clean(value).upper())


def canonical_url(value):
    value = clean(value)
    if not value:
        return ""
    p = urlsplit(value)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def record_key(record):
    number = normalize_bid_number(record.get("bid_number", ""))
    if number:
        return "bid:" + number
    url = canonical_url(record.get("url", ""))
    if url:
        return "url:" + url
    return "text:" + hashlib.sha256(clean(record.get("raw_text", "")).encode()).hexdigest()


def dedupe_records(records):
    result = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = record_key(record)
        if key in result:
            first_seen = result[key].get("first_seen") or record.get("first_seen")
            result[key].update({k: v for k, v in record.items() if v not in (None, "")})
            result[key]["first_seen"] = first_seen
        else:
            result[key] = dict(record)
            result[key]["id"] = key
    return result


def first_value(doc, *keys):
    for key in keys:
        value = doc.get(key, "")
        if isinstance(value, list):
            value = value[0] if value else ""
        if value not in (None, ""):
            return clean(value)
    return ""


def doc_fields(doc):
    return {
        "bid_number": first_value(doc, "b_bid_number"),
        "bid_id": first_value(doc, "b_id"),
        "category_raw": first_value(doc, "b_category_name"),
        "title": first_value(doc, "bbt_title"),
        "department": first_value(doc, "ba_official_details_deptName"),
        "ministry": first_value(doc, "ba_official_details_minName"),
        "start": first_value(doc, "final_start_date_sort"),
        "end": first_value(doc, "final_end_date_sort"),
    }


def buyer_matches(buyer_key, *sources):
    haystack = " ".join(clean(source) for source in sources if source)
    normalized_haystack = normalize(haystack)
    for alias in BUYERS[buyer_key]["aliases"]:
        alias_normalized = normalize(alias)
        if alias_normalized and alias_normalized in normalized_haystack:
            return True
    # Acronyms must be standalone tokens, not substrings of unrelated words.
    acronym = buyer_key
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(acronym) + r"(?![A-Za-z0-9])", haystack, re.I))


def category_for(text):
    low = clean(text).lower()
    for category, terms in SEARCH_TERMS.items():
        if any(term.lower() in low for term in terms):
            return category
    return ""


def location_matches(text):
    low = clean(text).lower()
    matches = []
    if re.search(r"\bmumbai\b|\b400\d{3}\b", low):
        matches.append("Mumbai")
    if re.search(r"\bpalghar\b|\b401\d{3}\b", low):
        matches.append("Palghar")
    if re.search(r"\bboisar\b", low):
        matches.append("Boisar")
    return list(dict.fromkeys(matches))


def parse_date(value):
    value = clean(value)
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(IST).isoformat(timespec="minutes")
    except ValueError:
        for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:19], fmt).replace(tzinfo=IST).isoformat(timespec="minutes")
            except ValueError:
                pass
    return value


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if clean(data):
            self.parts.append(clean(data))

    def text(self):
        return clean(" ".join(self.parts))


class AccessChallengeError(RuntimeError):
    pass


class GeMSession:
    def __init__(self):
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def request_bytes(self, url, data=None, headers=None, attempts=3):
        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        last_error = None
        for attempt in range(attempts):
            try:
                request = Request(url, data=data, headers=request_headers)
                with self.opener.open(request, timeout=40) as response:
                    return response.read()
            except HTTPError as exc:
                if exc.code in (401, 403, 429):
                    raise AccessChallengeError(
                        f"GeM returned HTTP {exc.code}; stopped without retrying or bypassing access controls"
                    ) from exc
                if exc.code == 404:
                    body = exc.read()
                    try:
                        json.loads(body.decode("utf-8", "replace"))
                        return body
                    except Exception:
                        raise
                raise
            except (URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"GeM network request failed after {attempts} attempts: {last_error}")

    def request(self, url, data=None, headers=None, attempts=3):
        raw = self.request_bytes(url, data=data, headers=headers, attempts=attempts)
        return raw.decode("utf-8", "replace")

    def init(self):
        html = self.request(ALL_BIDS, headers={"Accept": "text/html"})
        low = html.lower()
        if any(marker in low for marker in ("captcha", "access denied", "verify you are human")):
            raise AccessChallengeError("GeM displayed an access challenge; manual review required")
        match = re.search(r"csrf_bd_gem_nk.*?'([a-f0-9]{32})'", html, re.I)
        if not match:
            raise RuntimeError("Could not find GeM public CSRF token; portal markup may have changed")
        self.csrf = match.group(1)

    def search(self, term, page):
        if not self.csrf:
            self.init()
        payload = {
            "page": page,
            "param": {"searchBid": term, "searchType": "fullText"},
            "filter": {
                "bidStatusType": "ongoing_bids",
                "byType": "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": "Bid-End-Date-Latest",
            },
        }
        body = urlencode({
            "payload": json.dumps(payload, separators=(",", ":")),
            "csrf_bd_gem_nk": self.csrf,
        }).encode()
        raw = self.request(
            SEARCH_API,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Referer": ALL_BIDS,
                "Origin": BASE,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        data = json.loads(raw)
        if data.get("code") in (404, "404"):
            return 0, []
        if data.get("code") != 200:
            raise RuntimeError("GeM search returned unexpected response code " + str(data.get("code")))
        response = data.get("response", {}).get("response", {})
        return int(response.get("numFound", 0)), response.get("docs", [])

    def detail(self, bid_id):
        return self.request(
            BASE + "/showbidDocument/" + str(bid_id),
            headers={"Accept": "text/html", "Referer": ALL_BIDS},
        )


def scan_buyer(session, buyer_key, counters):
    buyer_name = BUYERS[buyer_key]["name"]
    page = 1
    total = None
    records = {}
    while True:
        if page > MAX_PAGES_PER_BUYER:
            raise RuntimeError(f"{buyer_key}: exceeded safety limit of {MAX_PAGES_PER_BUYER} pages; scan marked incomplete")
        page_total, docs = session.search(buyer_name, page)
        counters["pages_scanned"] += 1
        total = page_total if total is None else total
        counters["records_seen"] += len(docs)
        if not docs:
            if page == 1 and total == 0:
                break
            if page * 10 < total:
                raise RuntimeError(f"{buyer_key}: page {page} was empty before reported total {total}; incomplete scan")
            break

        for doc in docs:
            fields = doc_fields(doc)
            bid_id = fields["bid_id"]
            if not bid_id:
                continue
            bid_number = fields["bid_number"]
            key = record_key({"bid_number": bid_number, "url": BASE + "/showbidDocument/" + bid_id})
            if key in records:
                continue

            doc_text = json.dumps(doc, ensure_ascii=False)
            # Full official buyer name is used as the search query; this second
            # check prevents unrelated full-text matches from entering the feed.
            if not buyer_matches(buyer_key, doc_text, fields["department"], fields["ministry"]):
                continue

            try:
                detail_html = session.detail(bid_id)
                counters["details_checked"] += 1
                low_html = detail_html.lower()
                if any(marker in low_html for marker in ("captcha", "access denied", "verify you are human")):
                    raise AccessChallengeError("GeM displayed an access challenge on a bid detail page")
                parser = TextOnly()
                parser.feed(detail_html)
                detail_text = parser.text()
                pdf_texts, pdf_urls, pdf_errors = extract_detail_documents(
                    detail_html, BASE + "/showbidDocument/" + bid_id, session
                )
                counters["pdfs_checked"] += len(pdf_urls)
                if pdf_errors:
                    counters["warnings"].extend(pdf_errors[:2])
            except AccessChallengeError:
                raise
            except Exception as exc:
                counters["warnings"].append(
                    f"{bid_number or bid_id}: detail/PDF check incomplete: {str(exc)[:140]}"
                )
                detail_text = ""
                pdf_texts, pdf_urls = [], []

            combined = clean(" ".join([
                doc_text, fields["title"], fields["category_raw"],
                fields["department"], fields["ministry"], detail_text, " ".join(pdf_texts),
            ]))
            category = category_for(combined)
            locations = location_matches(combined)
            if not category or not locations:
                continue

            record = {
                "bid_number": bid_number,
                "title": fields["title"] or fields["category_raw"] or "GeM tender",
                "buyer": buyer_name,
                "buyer_code": buyer_key,
                "location": " / ".join(locations),
                "category": category,
                "bid_start_date": parse_date(fields["start"]),
                "bid_end_date": parse_date(fields["end"]),
                "url": BASE + "/showbidDocument/" + bid_id,
                "pdf_url": pdf_urls[0] if pdf_urls else "",
                "pdf_count": len(pdf_urls),
                "is_priority": True,
                "verification_status": "Official GeM listing checked",
                "source_type": "Official GeM public listing",
                "raw_text": combined[:12000],
                "first_seen": now_ist().isoformat(timespec="seconds"),
            }
            records[key] = record
            time.sleep(REQUEST_DELAY)

        if page * 10 >= total or len(docs) < 10:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    return records


def main():
    DATA.mkdir(exist_ok=True)
    tenders_path = DATA / "tenders.json"
    status_path = DATA / "status.json"
    try:
        old = json.loads(tenders_path.read_text(encoding="utf-8"))
    except Exception:
        old = []
    previous = dedupe_records(old)
    counters = {
        "pages_scanned": 0,
        "records_seen": 0,
        "details_checked": 0,
        "pdfs_checked": 0,
        "warnings": [],
    }
    started = now_ist()
    try:
        session = GeMSession()
        session.init()
        found = {}
        for buyer_key in ("NPCIL", "BARC", "AEES"):
            buyer_records = scan_buyer(session, buyer_key, counters)
            found.update(buyer_records)
            # Keep the organizations strictly sequential, never concurrent.
            time.sleep(REQUEST_DELAY)

        for key, item in found.items():
            old_item = previous.get(key, {})
            item["first_seen"] = old_item.get("first_seen") or item["first_seen"]
            item["is_new"] = key not in previous

        output = sorted(
            found.values(),
            key=lambda item: (item.get("bid_end_date") or "9999", item.get("buyer_code", ""), item.get("title", "")),
        )
        tenders_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        status = {
            "last_scan_success": True,
            "last_scan_ist": now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
            "scan_started_ist": started.strftime("%d-%b-%Y %I:%M:%S %p IST"),
            "buyers_scanned": ["NPCIL", "BARC", "AEES"],
            "pages_scanned": counters["pages_scanned"],
            "records_seen": counters["records_seen"],
            "details_checked": counters["details_checked"],
            "pdfs_checked": counters["pdfs_checked"],
            "matches_saved": len(found),
            "warning": "; ".join(counters["warnings"][:10]),
        }
    except Exception as exc:
        status = {
            "last_scan_success": False,
            "last_scan_ist": now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
            "buyers_scanned": ["NPCIL", "BARC", "AEES"],
            "pages_scanned": counters["pages_scanned"],
            "records_seen": counters["records_seen"],
            "details_checked": counters["details_checked"],
            "pdfs_checked": counters["pdfs_checked"],
            "matches_saved": 0,
            "warning": "Scan incomplete; previous tender data preserved. " + str(exc)[:300],
        }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    if not status["last_scan_success"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
