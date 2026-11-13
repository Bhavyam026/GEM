"""Extract public tender-document links and text from GeM bid detail HTML."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin
from io import BytesIO

class TenderLinks(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.current_href = ""
        self.current_text = ""
    def _add(self, href):
        full = urljoin(self.base_url, href)
        if full.startswith("https://bidplus.gem.gov.in/") and full not in self.links:
            self.links.append(full)
    def handle_data(self, data):
        self.current_text += " " + data
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_href and any(x in self.current_text.lower() for x in ("download", "document", "pdf")):
            self._add(self.current_href)
        if tag.lower() == "a":
            self.current_href = ""
            self.current_text = ""
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        label = (attrs.get("title", "") + " " + attrs.get("class", "")).lower()
        self.current_href = href
        self.current_text = ""
        if href and (".pdf" in href.lower() or "document" in label or "download" in label):
            self._add(href)

def extract_pdf_text(content: bytes) -> str:
    """Extract selectable text; OCR is deliberately not attempted in this free runner."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf dependency is not installed") from exc
    reader = PdfReader(BytesIO(content), strict=False)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return " ".join(" ".join(pages).split())

def extract_detail_documents(html: str, detail_url: str, session) -> tuple[list[str], list[str]]:
    parser = TenderLinks(detail_url)
    parser.feed(html)
    texts = []
    errors = []
    for url in parser.links[:5]:
        try:
            data = session.request_bytes(url, headers={"Accept": "application/pdf,*/*"})
            if data[:4] != b"%PDF":
                continue
            text = extract_pdf_text(data)
            if text:
                texts.append(text)
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:100]}")
    return texts, errors
