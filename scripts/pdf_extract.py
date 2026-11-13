"""Extract publicly accessible GeM PDF links and selectable text."""
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

    def _add(self, href: str):
        full = urljoin(self.base_url, href)
        if full.startswith("https://bidplus.gem.gov.in/") and full not in self.links:
            self.links.append(full)

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

    def handle_data(self, data):
        self.current_text += " " + data

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            if self.current_href and any(
                marker in self.current_text.lower() for marker in ("download", "document", "pdf")
            ):
                self._add(self.current_href)
            self.current_href = ""
            self.current_text = ""


def extract_pdf_text(content: bytes) -> str:
    """Extract selectable PDF text. Image-only/scanned PDFs need manual review."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf dependency is not installed") from exc
    reader = PdfReader(BytesIO(content), strict=False)
    return " ".join((page.extract_text() or "") for page in reader.pages).strip()


def extract_detail_documents(html: str, detail_url: str, session):
    """Return (PDF text, verified direct PDF URLs, errors).

    Only links hosted on the official GeM BidPlus domain are considered.
    A URL is returned only after its response has a PDF file signature.
    """
    parser = TenderLinks(detail_url)
    parser.feed(html)
    texts, verified_urls, errors = [], [], []
    for url in parser.links[:8]:
        try:
            content = session.request_bytes(
                url, headers={"Accept": "application/pdf,*/*"}, attempts=2
            )
            if content[:4] != b"%PDF":
                continue
            verified_urls.append(url)
            text = extract_pdf_text(content)
            if text:
                texts.append(text)
            else:
                errors.append(f"{url}: PDF has no selectable text; manual review/OCR required")
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:100]}")
    return texts, verified_urls, errors
