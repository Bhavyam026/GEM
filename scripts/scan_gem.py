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
SEARCH_API = BASE + "/search-bids"
IST = ZoneInfo("Asia/Kolkata")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
REQUEST_DELAY = 0.75
MAX_PAGES_PER_BUYER = 500

BUYERS = {
    "NPCIL": {
        "name": "NUCLEAR POWER CORPORATION OF INDIA LIMITED",
        "organization": "NUCLEAR POWER CORPORATION OF INDIA LIMITED",
        "aliases": ("NUCLEAR POWER CORPORATION OF INDIA LIMITED", "NPCIL"),
    },
    "BARC": {
        "name": "Bhabha Atomic Research Centre",
        "organization": "Bhabha Atomic Research Centre",
        "aliases": ("Bhabha Atomic Research Centre", "BARC"),
    },
    "AEES": {
        "name": "Atomic Energy Education Society (AEES)",
        "organization": "Atomic Energy Education Society (AEES)",
        "aliases": ("Atomic Energy Education Society (AEES)", "Atomic Energy Education Society", "AEES"),
    },
}

MINISTRY = "PMO"
DEPARTMENT = "Department of Atomic Energy"
PAGE_SIZE = 10

SEARCH_TERMS = {
    # Specific equipment/work categories take precedence over generic AMC/O&M wording.
    "CCTV & Surveillance": ("CCTV", "NVR", "DVR", "IP Camera", "Video Surveillance", "Surveillance Camera"),
    "Networking": ("Networking", "Network equipment", "Network", "LAN Switch", "Router", "Optical Fiber", "Network Switch", "Firewall"),
    "Electrical": ("O&M of Electrical Work", "Electrical Work", "Electrical Panel", "PLC SCADA", "Electrical Cable", "Earthing", "Electrical Wiring", "Lighting Fixture"),
    "Fire Safety": ("Fire Alarm", "Fire Safety", "Fire Extinguisher", "Smoke Detector", "Fire Detection"),
    "IT Assets": ("Desktop Computer", "Laptop", "Computer Monitor", "Printer", "IT Equipment", "Server"),
    "AMC & Maintenance": ("Annual Maintenance Contract", "Annual Maintenance", "AMC", "Comprehensive Annual Maintenance", "Comprehensive Maintenance Contract", "CAMC", "CMC", "Operation and Maintenance", "O&M", "Maintenance Services", "Maintenance Contract"),
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


def buyer_field_text(doc, fields):
    values = [fields.get("department", ""), fields.get("ministry", "")]
    for key, value in doc.items():
        key_low = key.lower()
        if any(marker in key_low for marker in ("org", "buyer", "agency", "purchaser")):
            if isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)
    return clean(" ".join(clean(value) for value in values if value))


def buyer_matches(buyer_key, buyer_fields, *detail_sources):
    all_text = " ".join(clean(source) for source in (buyer_fields, *detail_sources) if source)
    full_name = normalize(BUYERS[buyer_key]["name"])
    if full_name and full_name in normalize(all_text):
        return True
    # Accept an acronym only from explicit buyer/organisation fields, never
    # merely because it appears somewhere in a technical specification.
    acronym = buyer_key
    return bool(re.search(
        r"(?<![A-Za-z0-9])" + re.escape(acronym) + r"(?![A-Za-z0-9])",
        clean(buyer_fields), re.I
    ))


def target_ministry_department(ministry, department, *detail_sources):
    """Require the exact PMO / Department of Atomic Energy scope."""
    ministry_text = normalize(" ".join([clean(ministry), *[clean(x) for x in detail_sources if x]]))
    department_text = normalize(" ".join([clean(department), *[clean(x) for x in detail_sources if x]]))
    pmo_ok = bool(re.search(r"\bpmo\b", ministry_text)) or "prime minister s office" in ministry_text
    department_ok = "department of atomic energy" in department_text
    return pmo_ok and department_ok


def category_for(text):
    low = clean(text).lower()
    for category, terms in SEARCH_TERMS.items():
        if any(term.lower() in low for term in terms):
            return category
    return ""


def q_tier_for(*sources):
    """Return Q3 only when explicitly evidenced; Q2 is rejected, conflicts are manual."""
    text = " ".join(clean(source) for source in sources if source)
    tiers = set(re.findall(r"\bQ\s*[-:]?\s*([234])\b", text, re.I))
    if len(tiers) != 1:
        return "manual_review"
    tier = next(iter(tiers))
    return "Q" + tier if tier == "3" else "rejected"


def office_name_for(*sources):
    """Read GeM's Office Name separately from its buyer organisation."""
    text = " ".join(clean(source) for source in sources if source)
    match = re.search(
        r"(?:Office Name|कार्यालय का नाम)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9 .&()/-]{0,30}?)(?=\s+(?:Contact|Grievance|Organisation|Department|Item Category)\b|[\u0900-\u097F]|$)",
        text, re.I
    )
    return clean(match.group(1)).strip(" .|:-") if match else ""


def location_matches(text):
    low = clean(text).lower()
    matches = []
    if re.search(r"\bmumbai\b|\b400[01]\d{2}\b", low):
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
                parsed = datetime.strptime(value[:19], fmt)
                if fmt in ("%d-%m-%Y", "%Y-%m-%d"):
                    return parsed.date().isoformat()
                return parsed.replace(tzinfo=IST).isoformat(timespec="minutes")
            except ValueError:
                pass
    return value

def bid_is_active(value):
    """Keep date-only deadlines through the end of that IST day."""
    value = clean(value)
    if not value:
        return True
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.strptime(value, "%Y-%m-%d").date() >= now_ist().date()
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST) >= now_ist()
    except ValueError:
        return True


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
        token_patterns = (
            r'name=["\']csrf_bd_gem_nk["\']\s+value=["\']([^"\']+)',
            r'value=["\']([^"\']+)["\']\s+name=["\']csrf_bd_gem_nk["\']',
            r'csrf_bd_gem_nk["\']?\s*[:=]\s*["\']([a-f0-9]{32})',
        )
        token = ""
        for pattern in token_patterns:
            match = re.search(pattern, html, re.I)
            if match:
                token = match.group(1)
                break
        if not token:
            raise RuntimeError("Could not find GeM CSRF token in fresh public session; portal markup may have changed")
        self.csrf = token

    @staticmethod
    def build_advance_payload(buyer_key, page):
        if buyer_key not in BUYERS:
            raise ValueError("Unsupported buyer: " + str(buyer_key))
        return {
            "searchType": "ministry-search",
            "ministry": MINISTRY,
            "buyerState": "",
            "organization": BUYERS[buyer_key]["organization"],
            "department": DEPARTMENT,
            "bidEndFromMin": "",
            "bidEndToMin": "",
            "page": int(page),
        }

    def search(self, buyer_key, page):
        if not self.csrf:
            self.init()
        payload = self.build_advance_payload(buyer_key, page)
        body = urlencode({
            "payload": json.dumps(payload, separators=(",", ":")),
            "csrf_bd_gem_nk": self.csrf,
        }).encode()
        raw = self.request(
            SEARCH_API,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
                "Referer": BASE + "/advance-search",
                "Origin": BASE,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        data = json.loads(raw)
        if data.get("code") != 200:
            raise RuntimeError("GeM Advance Search returned unexpected response code " + str(data.get("code")))
        response = data.get("response", {}).get("response", {})
        if not isinstance(response, dict):
            raise RuntimeError("GeM Advance Search response structure changed")
        docs = response.get("docs")
        if not isinstance(docs, list):
            raise RuntimeError("GeM Advance Search did not return a docs array")
        return {
            "total": int(response.get("numFound", 0)),
            "start": int(response.get("start", 0)),
            "current_page": data.get("current_page"),
            "docs": docs,
        }

    def detail(self, bid_id):
        return self.request(
            BASE + "/showbidDocument/" + str(bid_id),
            headers={"Accept": "text/html", "Referer": ALL_BIDS},
        )


def scan_buyer(session, buyer_key, counters):
    buyer_name = BUYERS[buyer_key]["name"]
    page = 1
    total = 0
    records = {}
    while True:
        if page > MAX_PAGES_PER_BUYER:
            raise RuntimeError(f"{buyer_key}: exceeded safety limit of {MAX_PAGES_PER_BUYER} pages; scan marked incomplete")
        result = session.search(buyer_key, page)
        page_total, start, current_page, docs = (
            result["total"], result["start"], result["current_page"], result["docs"]
        )
        expected_start = (page - 1) * PAGE_SIZE
        if start != expected_start:
            raise RuntimeError(
                f"{buyer_key}: expected result start {expected_start} on page {page}, got {start}; scan incomplete"
            )
        if current_page is not None and int(current_page) != page - 1:
            raise RuntimeError(
                f"{buyer_key}: GeM current_page mismatch on page {page}; scan incomplete"
            )
        # GeM's observed numFound changed between adjacent requests (447/448).
        # Retain the largest count seen so pagination cannot stop prematurely.
        total = max(total, page_total)
        counters["pages_scanned"] += 1
        counters["records_seen"] += len(docs)
        if not docs:
            if page == 1 and total == 0:
                break
            if start < total:
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

            try:
                detail_html = session.detail(bid_id)
                counters["details_checked"] += 1
                low_html = detail_html.lower()
                if any(marker in low_html for marker in ("captcha", "access denied", "verify you are human")):
                    raise AccessChallengeError("GeM displayed an access challenge on a bid detail page")
                parser = TextOnly()
                parser.feed(detail_html)
                detail_text = parser.text()
                pdf_texts, pdf_urls, pdf_errors, pdf_local_path = extract_detail_documents(
                    detail_html, BASE + "/showbidDocument/" + bid_id, session, bid_number
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
                pdf_texts, pdf_urls, pdf_local_path = [], [], ""
            finally:
                time.sleep(REQUEST_DELAY)

            combined = clean(" ".join([
                doc_text, fields["title"], fields["category_raw"],
                fields["department"], fields["ministry"], detail_text, " ".join(pdf_texts),
            ]))
            # Confirm the buyer against the full public detail/document text,
            # not just the search result row (which may omit the organisation).
            if not buyer_matches(buyer_key, buyer_field_text(doc, fields), detail_text, " ".join(pdf_texts)):
                continue
            if not target_ministry_department(fields["ministry"], fields["department"], detail_text, " ".join(pdf_texts)):
                continue
            category = category_for(combined)
            # The Q3-only rule applies to CCTV product/category bids only.
            # Facility-management and other service tenders have no Q-tier gate.
            q_tier = "Not applicable"
            if category == "CCTV & Surveillance":
                q_tier = q_tier_for(fields["category_raw"], detail_text, " ".join(pdf_texts))
                if q_tier != "Q3":
                    continue
            # Geography must be evidenced by text extracted from the official
            # downloaded GeM PDF, not merely the listing/search result.
            locations = location_matches(" ".join(pdf_texts))
            if not category or not locations:
                continue

            record = {
                "bid_number": bid_number,
                "title": fields["title"] or fields["category_raw"] or "GeM tender",
                "buyer": buyer_name,
                "buyer_code": buyer_key,
                "office_name": office_name_for(detail_text, " ".join(pdf_texts)),
                "location": " / ".join(locations),
                "category": category,
                "gem_category_tier": q_tier,
                "bid_start_date": parse_date(fields["start"]),
                "bid_end_date": parse_date(fields["end"]),
                "url": BASE + "/showbidDocument/" + bid_id,
                "pdf_url": pdf_urls[0] if pdf_urls else "",
                "pdf_count": len(pdf_urls),
                "pdf_local_path": pdf_local_path,
                "pdf_verified": bool(pdf_local_path),
                "is_priority": True,
                "verification_status": "Official GeM listing checked",
                "source_type": "Official GeM public listing",
                "raw_text": combined[:12000],
                "first_seen": now_ist().isoformat(timespec="seconds"),
            }
            records[key] = record
            time.sleep(REQUEST_DELAY)

        if start + len(docs) >= total:
            break
        if len(docs) < PAGE_SIZE:
            raise RuntimeError(
                f"{buyer_key}: only {len(docs)} records on page {page} while total={total}; refusing an incomplete scan"
            )
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
    try:
        previous_status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        previous_status = {}
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

        # Expired tenders and their PDF copies leave the active dashboard.
        active_found = {
            key: item for key, item in found.items()
            if bid_is_active(item.get("bid_end_date", ""))
        }
        output = sorted(
            active_found.values(),
            key=lambda item: (item.get("bid_end_date") or "9999", item.get("buyer_code", ""), item.get("title", "")),
        )
        tenders_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Cleanup is deliberately after a complete successful scan only.
        keep_pdfs = {
            str(item.get("pdf_local_path", ""))
            for item in output if item.get("pdf_verified") is True
        }
        pdf_dir = DATA / "pdfs"
        if pdf_dir.exists():
            for pdf_file in pdf_dir.glob("*.pdf"):
                relative = "data/pdfs/" + pdf_file.name
                if relative not in keep_pdfs:
                    pdf_file.unlink()
        status = {
            "last_scan_success": True,
            "last_scan_ist": now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
            "last_success_ist": now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
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
            "last_success_ist": previous_status.get("last_success_ist", ""),
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
