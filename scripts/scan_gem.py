#!/usr/bin/env python3
"""Best-effort collector for visible public GeM ongoing-bid result rows.

Does not solve or bypass CAPTCHA, OTP, authentication, or access controls.
The portal's public markup can change; validate the first workflow run.
"""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://bidplus.gem.gov.in/advance-search"
IST = ZoneInfo("Asia/Kolkata")
LOCATIONS = ("mumbai", "palghar")
PRIORITY = ("nuclear power corporation", "npcil", "bhabha atomic research", "barc", "atomic energy education", "aees")
KEYWORDS = {
    "CCTV & Surveillance": ("cctv", "surveillance", "nvr", "dvr", "video camera", "ip camera"),
    "Networking": ("network", "lan", "router", "switch", "fiber optic", "fibre optic", "ethernet", "optical fibre"),
    "Electrical": ("electrical", "electric", "panel", "plc", "scada", "cable", "wiring", "fan", "light", "earthing"),
    "Fire Safety": ("fire alarm", "fire safety", "fire extinguisher", "smoke detector", "fire fighting"),
    "IT Assets": ("desktop", "computer", "laptop", "monitor", "printer", "server", "workstation", "it equipment"),
}
def now_ist(): return datetime.now(IST)
def clean(s): return re.sub(r"\s+", " ", s or "").strip()
def category(text):
    t=text.lower()
    for name, words in KEYWORDS.items():
        if any(w in t for w in words): return name
    return None
def bid_no(text):
    patterns=(r"\bGEM/\d{4}/B/\d+\b", r"\bGEMC-\d+\b", r"\b\d{10,}\b")
    for p in patterns:
        m=re.search(p,text,re.I)
        if m: return m.group(0)
    return ""
def extract_rows(page):
    rows=[]
    # Prefer tabular result rows; avoid collecting navigation/footer text.
    for table in page.locator("table").all():
        for tr in table.locator("tr").all():
            try:
                txt=clean(tr.inner_text(timeout=1500))
                if len(txt)>35 and re.search(r"\b(GEM/|GEMC-|bid|tender)\b",txt,re.I):
                    href=""
                    links=tr.locator("a[href]")
                    if links.count():
                        href=links.first.get_attribute("href") or ""
                        if href.startswith("/"): href="https://bidplus.gem.gov.in"+href
                    rows.append({"raw":txt,"url":href})
            except Exception: pass
    return rows
def is_challenge(page):
    try: text=page.locator("body").inner_text(timeout=3000).lower()
    except Exception: return False
    return any(x in text for x in ("verify you are human","captcha","security check","access denied","otp verification"))
def next_page(page):
    # Only use a visible, enabled next control; do not guess page URLs.
    candidates = [
        page.get_by_role("link", name=re.compile(r"^next\b|^›$|^»$", re.I)),
        page.get_by_role("button", name=re.compile(r"^next\b|^›$|^»$", re.I)),
        page.locator("a[rel=next],button[aria-label*=Next i],a[aria-label*=Next i]")
    ]
    for loc in candidates:
        try:
            for i in range(min(loc.count(),3)):
                el=loc.nth(i)
                if el.is_visible() and el.is_enabled():
                    label=clean((el.inner_text(timeout=500) or "")+" "+(el.get_attribute("class") or ""))
                    if "disabled" in label.lower(): continue
                    return el
        except Exception: pass
    return None
def parse_row(row):
    raw=row["raw"]; low=raw.lower()
    cat=category(raw)
    if not cat or not any(x in low for x in LOCATIONS): return None
    org=next((x for x in PRIORITY if x in low),None)
    number=bid_no(raw)
    # Preserve full row text because portal column labels/layout can vary.
    title=raw[:240]
    return {"id":number or row.get("url") or str(abs(hash(raw))),"bid_number":number,"title":title,
            "buyer":next((label for label in ("NPCIL","BARC","AEES") if label.lower() in low), ""),
            "location":"Mumbai" if "mumbai" in low else "Palghar",
            "category":cat,"bid_end_date":"","url":row.get("url") or URL,
            "is_priority":bool(org),"is_new":False,"raw_text":raw}
def main():
    DATA.mkdir(exist_ok=True)
    old=[]
    try: old=json.loads((DATA/"tenders.json").read_text(encoding="utf-8"))
    except Exception: pass
    previous={x.get("id"):x for x in old}
    seen={}; warnings=[]; pages=0; raw_count=0; success=False
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(locale="en-IN")
        try:
            page.goto(URL,wait_until="domcontentloaded",timeout=90000)
            page.wait_for_timeout(5000)
            if is_challenge(page):
                raise RuntimeError("GeM displayed a CAPTCHA, login, or access challenge. No bypass attempted; manual review required.")
            # The page may load the ongoing-bid results by default. If a visible
            # search form is present, leave its filters untouched rather than
            # submitting unverified field mappings.
            for page_no in range(1,101):
                pages=page_no
                if is_challenge(page):
                    raise RuntimeError("GeM access challenge detected during pagination.")
                rows=extract_rows(page); raw_count += len(rows)
                for row in rows:
                    item=parse_row(row)
                    if item:
                        key=item["id"]
                        if key in previous:
                            item["first_seen"]=previous[key].get("first_seen") or now_ist().isoformat()
                        else:
                            item["first_seen"]=now_ist().isoformat(); item["is_new"]=True
                        seen[key]=item
                nxt=next_page(page)
                if not nxt: break
                try:
                    nxt.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded",timeout=10000)
                    page.wait_for_timeout(1200)
                except Exception as e:
                    warnings.append("Pagination stopped: "+str(e)[:180]); break
            success=True
        finally:
            browser.close()
    # Keep prior records that may have fallen off the ongoing-bids first pages;
    # do not silently delete potentially active records during transient portal gaps.
    merged={x.get("id"):x for x in old if x.get("id")}
    merged.update(seen)
    output=sorted(merged.values(),key=lambda x:(not x.get("is_priority",False),x.get("bid_end_date") or "9999",x.get("title","")))
    (DATA/"tenders.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    status={"last_scan_success":success,"last_scan_ist":now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
            "pages_scanned":pages,"records_seen":raw_count,"matches_saved":len(seen),
            "warning":"; ".join(warnings) if warnings else ("No matching rows detected. Verify GeM result layout and location columns." if not seen else "")}
    (DATA/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(status,indent=2))
    if not success: sys.exit(2)
if __name__=="__main__": main()
