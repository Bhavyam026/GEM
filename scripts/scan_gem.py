#!/usr/bin/env python3
"""Cloud-only public GeM BidPlus collector. Never bypasses CAPTCHA/login/access controls."""
from __future__ import annotations
import hashlib, json, re, sys, time
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, HTTPCookieProcessor, build_opener
from urllib.error import HTTPError, URLError
from http.cookiejar import CookieJar
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from scripts.pdf_extract import extract_detail_documents
except ModuleNotFoundError:
    from pdf_extract import extract_detail_documents

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
BASE="https://bidplus.gem.gov.in"
ALL_BIDS=BASE+"/all-bids"
SEARCH_API=BASE+"/all-bids-data"
IST=ZoneInfo("Asia/Kolkata")
PRIORITY=("nuclear power corporation","npcil","bhabha atomic research","barc","atomic energy education","aees")
SEARCH_TERMS={
 "CCTV & Surveillance":("CCTV","NVR","DVR","IP Camera","Video Surveillance"),
 "Networking":("Networking","LAN Switch","Router","Optical Fiber","Network Switch"),
 "Electrical":("Electrical Panel","PLC SCADA","Electrical Cable","Earthing","Electrical Wiring"),
 "Fire Safety":("Fire Alarm","Fire Safety","Fire Extinguisher","Smoke Detector"),
 "IT Assets":("Desktop Computer","Laptop","Computer Monitor","Printer","IT Equipment"),
}
LOCATIONS=("mumbai","palghar","boisar","401","400")
def now_ist(): return datetime.now(IST)
def clean(s): return re.sub(r"\s+"," ",s or "").strip()
def normalize_bid_number(value): return re.sub(r"\s+","",clean(value).upper())
def canonical_url(value):
 value=clean(value)
 if not value:return ""
 p=urlsplit(value)
 return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip("/"),"",""))
def record_key(record):
 n=normalize_bid_number(record.get("bid_number",""))
 if n:return "bid:"+n
 u=canonical_url(record.get("url",""))
 if u:return "url:"+u
 return "text:"+hashlib.sha256(clean(record.get("raw_text","")).encode()).hexdigest()
def dedupe_records(records):
 out={}
 for rec in records:
  if not isinstance(rec,dict):continue
  k=record_key(rec)
  if k in out:
   first=out[k].get("first_seen") or rec.get("first_seen")
   out[k].update({a:b for a,b in rec.items() if b not in (None,"")})
   out[k]["first_seen"]=first
  else:
   out[k]=dict(rec);out[k]["id"]=k
 return out
def category(text):
 low=text.lower()
 for cat,terms in SEARCH_TERMS.items():
  if any(t.lower() in low for t in terms):return cat
 return None
def date_value(value):
 value=clean(value)
 for fmt in ("%Y-%m-%dT%H:%M:%S%z","%Y-%m-%d %H:%M:%S","%d-%m-%Y %H:%M:%S","%d-%m-%Y","%Y-%m-%d"):
  try:return datetime.strptime(value[:25],fmt).date().isoformat()
  except Exception:pass
 return ""
class TextOnly(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,data): 
  if clean(data):self.parts.append(clean(data))
 def text(self):return clean(" ".join(self.parts))
class GeMSession:
 def __init__(self):
  self.jar=CookieJar();self.opener=build_opener(HTTPCookieProcessor(self.jar));self.csrf=""
 def request_bytes(self,url,headers=None):
  h={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
  if headers:h.update(headers)
  req=Request(url,headers=h)
  with self.opener.open(req,timeout=45) as response:return response.read()
 def request(self,url,data=None,headers=None):
  h={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
  if headers:h.update(headers)
  req=Request(url,data=data,headers=h)
  try:
   with self.opener.open(req,timeout=35) as response:return response.read().decode("utf-8","replace")
  except HTTPError as e:
   if e.code==404:
    body=e.read().decode("utf-8","replace")
    try:json.loads(body);return body
    except Exception:raise
   raise
 def init(self):
  html=self.request(ALL_BIDS,headers={"Accept":"text/html"})
  m=re.search(r"csrf_bd_gem_nk.*?'([a-f0-9]{32})'",html)
  if not m:raise RuntimeError("Could not find public GeM CSRF token; portal markup may have changed")
  self.csrf=m.group(1)
 def post_json(self,payload):
  if not self.csrf:self.init()
  body=urlencode({"payload":json.dumps(payload,separators=(",",":")),"csrf_bd_gem_nk":self.csrf}).encode()
  raw=self.request(SEARCH_API,data=body,headers={"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json","Referer":ALL_BIDS,"Origin":BASE,"X-Requested-With":"XMLHttpRequest"})
  return json.loads(raw)
 def search(self,term,page):
  data=self.post_json({"page":page,"param":{"searchBid":term,"searchType":"fullText"},"filter":{"bidStatusType":"ongoing_bids","byType":"all","highBidValue":"","byEndDate":{"from":"","to":""},"sort":"Bid-End-Date-Latest"}})
  if data.get("code") in (404,"404"):return 0,[]
  if data.get("code")!=200:raise RuntimeError("GeM search returned unexpected response code "+str(data.get("code")))
  r=data.get("response",{}).get("response",{})
  return int(r.get("numFound",0)),r.get("docs",[])
 def detail(self,bid_id):
  return self.request(BASE+"/showbidDocument/"+str(bid_id),headers={"Accept":"text/html","Referer":ALL_BIDS})
def doc_fields(doc):
 def val(k,default=""):
  x=doc.get(k,default)
  return x[0] if isinstance(x,list) and x else (x if isinstance(x,str) else default)
 return {"bid_number":val("b_bid_number"),"bid_id":val("b_id"),"category_raw":val("b_category_name"),
         "title":val("bbt_title"),"department":val("ba_official_details_deptName"),
         "ministry":val("ba_official_details_minName"),"start":val("final_start_date_sort"),
         "end":val("final_end_date_sort")}
def main():
 DATA.mkdir(exist_ok=True)
 try:old=json.loads((DATA/"tenders.json").read_text(encoding="utf-8"))
 except Exception:old=[]
 previous=dedupe_records(old);found={};terms=[(c,t) for c,ts in SEARCH_TERMS.items() for t in ts]
 session=GeMSession();pages=0;docs_seen=0;details_seen=0;warnings=[];scan_started=now_ist()
 try:
  session.init()
  # Each keyword is paginated to the portal's reported final page.
  for expected_cat,term in terms:
   page=1;total=0
   while True:
    total,docs=session.search(term,page);pages+=1
    if not docs:break
    docs_seen+=len(docs)
    for doc in docs:
     f=doc_fields(doc);bid_id=f["bid_id"]
     key=record_key({"bid_number":f["bid_number"],"url":BASE+"/showbidDocument/"+bid_id})
     if key in found:continue
     try:
      detail_html=session.detail(bid_id) if bid_id else ""
      details_seen+=1
      parser=TextOnly();parser.feed(detail_html);detail_text=parser.text()
      pdf_texts,pdf_errors=extract_detail_documents(detail_html,BASE+"/showbidDocument/"+str(bid_id),session)
      if pdf_errors:warnings.extend(pdf_errors[:2])
      pdf_text=" ".join(pdf_texts)
      if pdf_text:detail_text=clean(detail_text+" "+pdf_text)
     except Exception as exc:
      warnings.append("Bid detail unavailable for "+(f["bid_number"] or bid_id)+": "+str(exc)[:120])
      detail_text=""
     combined=clean(" ".join([f["title"],f["category_raw"],f["department"],f["ministry"],detail_text]))
     cat=category(combined) or expected_cat
     low=combined.lower()
     matched_locs=[]
     if "mumbai" in low or re.search(r"\b400\d{3}\b",low):matched_locs.append("Mumbai")
     if "palghar" in low or re.search(r"\b401\d{3}\b",low):matched_locs.append("Palghar")
     if not matched_locs:continue
     org=next((p for p in PRIORITY if p in low),None)
     end=date_value(f["end"])
     url=BASE+"/showbidDocument/"+bid_id if bid_id else ""
     item={"bid_number":f["bid_number"],"title":f["title"] or f["category_raw"],
      "buyer":f["department"] or f["ministry"],"location":" / ".join(matched_locs),
      "category":cat,"bid_end_date":end,"url":url,"is_priority":bool(org),
      "is_new":False,"raw_text":combined,"id":key}
     if key in previous:
      item["first_seen"]=previous[key].get("first_seen") or now_ist().isoformat()
     else:item["first_seen"]=now_ist().isoformat();item["is_new"]=True
     found[key]=item
     time.sleep(0.25)
    if len(docs)<10 or page*10>=total:break
    page+=1;time.sleep(0.35)
  # Only publish a successful complete keyword sweep; preserve old data on failures.
  merged=dedupe_records(old)
  for rec in merged.values():rec["is_new"]=False
  for key,item in found.items():
   if key in merged:
    first=merged[key].get("first_seen") or item["first_seen"]
    merged[key].update({k:v for k,v in item.items() if v not in (None,"")})
    merged[key]["first_seen"]=first;merged[key]["is_new"]=False
   else:merged[key]=item
  output=sorted(merged.values(),key=lambda x:(not x.get("is_priority",False),x.get("bid_end_date") or "9999",x.get("title","")))
  (DATA/"tenders.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  status={"last_scan_success":True,"last_scan_ist":now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
   "pages_scanned":pages,"records_seen":docs_seen,"details_checked":details_seen,"matches_saved":len(found),
   "warning":"; ".join(warnings[:10]) if warnings else ""}
 except Exception as exc:
  status={"last_scan_success":False,"last_scan_ist":now_ist().strftime("%d-%b-%Y %I:%M:%S %p IST"),
   "pages_scanned":pages,"records_seen":docs_seen,"details_checked":details_seen,"matches_saved":0,
   "warning":"GeM public search failed; previous tender data preserved. "+str(exc)[:300]}
 (DATA/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps(status,indent=2))
 if not status["last_scan_success"]:sys.exit(2)
if __name__=="__main__":main()
