"""Extract publicly accessible GeM PDF links, save exact PDF bytes, and extract text."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from io import BytesIO
from pathlib import Path


class TenderLinks(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.current_href = ""
        self.current_text = ""

    # GeM sometimes includes legacy conditional/marked-section declarations
    # (for example <![if ...]>). Python 3.8's ParserBase does not reliably
    # handle unknown marked-section names and can raise TypeError. Consume
    # only the declaration wrapper, then continue parsing its HTML contents.
    def parse_html_declaration(self, i):
        if self.rawdata.startswith("<![", i):
            end = self.rawdata.find(">", i + 3)
            return -1 if end < 0 else end + 1
        return super().parse_html_declaration(i)

    def error(self, message):
        return

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


def safe_pdf_filename(bid_number: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(bid_number or "").strip()).strip("_")
    if not safe:
        raise ValueError("Cannot save a tender PDF without its Bid Number")
    return safe + ".pdf"


def save_original_pdf(content: bytes, bid_number: str, data_dir: Path | None = None) -> str:
    """Atomically save the exact downloaded PDF bytes under its Bid Number."""
    if not isinstance(content, bytes) or not content.startswith(b"%PDF"):
        raise ValueError("Downloaded document is not a valid PDF signature")
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("PDF exceeds 25 MB safety limit")

    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[1] / "data"
    target_dir = Path(data_dir) / "pdfs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_pdf_filename(bid_number)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(content)
        saved = temporary.read_bytes()
        if saved != content:
            raise IOError("Saved PDF bytes do not match the original download")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "data/pdfs/" + target.name


def extract_detail_documents(html: str, detail_url: str, session, bid_number: str = ""):
    """Return (PDF text, verified direct PDF URLs, errors, local PDF path).

    Only official GeM BidPlus links are accepted. The first PDF that passes the
    signature and size checks is stored byte-for-byte under data/pdfs using its Bid Number.
    """
    parser = TenderLinks(detail_url)
    parser.feed(html)
    texts, verified_urls, errors = [], [], []
    local_path = ""
    for url in parser.links[:8]:
        try:
            content = session.request_bytes(
                url, headers={"Accept": "application/pdf,*/*"}, attempts=2
            )
            if not content.startswith(b"%PDF"):
                errors.append(f"{url}: response did not contain a PDF signature")
                continue
            if len(content) > 25 * 1024 * 1024:
                errors.append(f"{url}: PDF exceeds 25 MB safety limit")
                continue
            verified_urls.append(url)
            if not local_path:
                local_path = save_original_pdf(content, bid_number)
            text = extract_pdf_text(content)
            if text:
                texts.append(text)
            else:
                errors.append(f"{url}: PDF has no selectable text; manual review/OCR required")
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:100]}")
    return texts, verified_urls, errors, local_path
