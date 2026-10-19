#!/usr/bin/env python3
"""Extract clean, structured text from a literary source file for translation.

Usage:
    python extract.py <file.(docx|epub|pdf|txt)> [--chunk-chars N] [--out blocks.json]

Output: JSON to stdout (or --out) of the form
    {
      "source": "<path>",
      "title": "<detected title or filename>",
      "char_count": <int>,
      "blocks": [ {"type": "heading|body|scene_break", "level": int, "text": str}, ... ],
      "chunks": [ [block, ...], ... ]   # only present when --chunk-chars given
    }

Design notes (addresses review findings):
  * EPUB is read in SPINE order, not item-iteration order (reading order bug).
  * PDF goes through a cleanup pass: form-feed page split, running header/footer
    and bare page-number removal, de-hyphenation of line-broken words.
  * DOCX preserves heading levels, centered scene breaks, and *italic* runs
    (italics carry meaning in literature: emphasis, titles, interior monologue).
  * Italics are marked inline with Markdown-style *asterisks* so downstream
    agents and the .docx writer can round-trip them.
"""
import sys, os, re, json, argparse, subprocess
from collections import Counter

SCENE_BREAK = {"type": "scene_break", "level": 0, "text": "* * *"}


# ---------------------------------------------------------------- DOCX
def extract_docx(path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document(path)
    blocks = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        style = (p.style.name or "").lower()

        # Centered short line with no alphanumerics, or classic break glyphs.
        is_break = (
            p.alignment == WD_ALIGN_PARAGRAPH.CENTER
            and len(txt) <= 5
            and not re.search(r"\w", txt)
        ) or re.fullmatch(r"[\*\-—•\s]{2,}", txt or "x") is not None and txt != ""

        if not txt:
            continue
        if style.startswith("heading") or style == "title":
            level = 1
            m = re.search(r"(\d+)", style)
            if m:
                level = int(m.group(1))
            blocks.append({"type": "heading", "level": level, "text": txt})
            continue
        if is_break:
            blocks.append(dict(SCENE_BREAK))
            continue

        # Reconstruct paragraph with italic markers from runs.
        parts = []
        for run in p.runs:
            t = run.text
            if not t:
                continue
            if run.italic:
                t = f"*{t}*"
            parts.append(t)
        text = ("".join(parts)).strip() or txt
        # collapse adjacent italic markers like *a**b* -> *ab*
        text = re.sub(r"\*\*", "", text)
        blocks.append({"type": "body", "level": 0, "text": text})
    return blocks


# ---------------------------------------------------------------- EPUB
def extract_epub(path):
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(path)
    # Map manifest id -> item, then walk the SPINE for true reading order.
    id_map = {item.get_id(): item for item in book.get_items()}
    blocks = []
    skip_pat = re.compile(r"(copyright|cover|title\s*page|toc|contents|colophon|acknowledg)", re.I)

    for idref, _linear in book.spine:
        item = id_map.get(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = (item.get_name() or "").lower()
        soup = BeautifulSoup(item.get_content(), "html.parser")
        # Drop obvious front/back matter files by filename.
        if skip_pat.search(name):
            # still allow if it actually contains a lot of prose
            if len(soup.get_text(strip=True)) < 1200:
                continue
        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote"]):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue
            tag = el.name
            if tag in ("h1", "h2", "h3", "h4"):
                blocks.append({"type": "heading", "level": int(tag[1]), "text": txt})
            else:
                # mark <em>/<i> as italics
                for it in el.find_all(["em", "i"]):
                    if it.string:
                        it.string.replace_with(f"*{it.get_text()}*")
                txt = el.get_text(" ", strip=True)
                blocks.append({"type": "body", "level": 0, "text": txt})
    return blocks


# ---------------------------------------------------------------- PDF
def _hdr_key(line):
    """Normalize an edge line for running-header detection: drop digits, roman
    numerals and punctuation so 'THE NOVEL   3' and 'THE NOVEL   4' collapse to
    the same key."""
    return re.sub(r"[\divxlcdm\W_]+", " ", line, flags=re.I).strip().lower()


def _clean_pdf_pages(raw):
    """raw text from pdftotext (-layout), pages separated by form feed."""
    pages = raw.split("\f")
    # Detect running headers/footers: first/last line whose digit-stripped stem
    # repeats across many pages (handles "Title   <pageno>" headers).
    edge_keys = Counter()
    for pg in pages:
        lines = [l.strip() for l in pg.splitlines() if l.strip()]
        if lines:
            for s in {lines[0], lines[-1]}:
                k = _hdr_key(s)
                if k:
                    edge_keys[k] += 1
    npages = max(1, len([p for p in pages if p.strip()]))
    thresh = max(2, round(npages * 0.4))
    running = {k for k, c in edge_keys.items() if c >= thresh}

    cleaned_lines = []
    for pg in pages:
        lines = [l.rstrip() for l in pg.splitlines()]
        # strip leading/trailing blank lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        for i, l in enumerate(lines):
            s = l.strip()
            edge = i == 0 or i == len(lines) - 1
            if edge and (
                _hdr_key(s) in running
                or re.fullmatch(r"[ivxlcdm\d\s\.\-—]{1,8}", s, re.I)
            ):
                continue  # drop running head/foot and bare page numbers
            cleaned_lines.append(l)
        cleaned_lines.append("")  # page boundary -> blank

    text = "\n".join(cleaned_lines)
    # De-hyphenate words broken across line ends: "consid-\nered" -> "considered"
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
    # Join wrapped lines within a paragraph (line not ending in sentence punctuation,
    # next line starting lowercase) into spaces; keep blank lines as paragraph breaks.
    out, buf = [], []
    for line in text.split("\n"):
        if not line.strip():
            if buf:
                out.append(" ".join(buf)); buf = []
            continue
        buf.append(line.strip())
    if buf:
        out.append(" ".join(buf))
    return out


def extract_pdf(path):
    blocks = []
    raw = None
    try:
        raw = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
            capture_output=True, text=True, encoding="utf-8", timeout=600
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        raw = None
    if not raw or not raw.strip():
        # fallback to PyMuPDF
        import fitz
        doc = fitz.open(path)
        raw = "\f".join(page.get_text("text") for page in doc)
    for para in _clean_pdf_pages(raw):
        para = para.strip()
        if not para:
            continue
        # Heuristic: short ALL-CAPS or "Chapter N" line => heading.
        if re.match(r"(chapter|part|book)\s+[\divxlc]+", para, re.I) or (
            len(para) < 60 and para.isupper()
        ):
            blocks.append({"type": "heading", "level": 1, "text": para.title()})
        else:
            blocks.append({"type": "body", "level": 0, "text": para})
    return blocks


# ---------------------------------------------------------------- TXT
def extract_txt(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    blocks = []
    for para in re.split(r"\n\s*\n", raw):
        para = para.strip()
        if not para:
            continue
        if re.fullmatch(r"[\*\-—\s]{2,}", para):
            blocks.append(dict(SCENE_BREAK))
        else:
            blocks.append({"type": "body", "level": 0, "text": re.sub(r"\s*\n\s*", " ", para)})
    return blocks


# ---------------------------------------------------------------- chunking
def chunk_blocks(blocks, max_chars):
    """Group blocks into chunks <= max_chars, never splitting a block.
    A chunk always starts fresh on a heading so chapters/sections stay intact."""
    chunks, cur, size = [], [], 0
    for b in blocks:
        blen = len(b["text"]) + 1
        if cur and (size + blen > max_chars or b["type"] == "heading" and size > max_chars * 0.5):
            chunks.append(cur); cur, size = [], 0
        cur.append(b); size += blen
    if cur:
        chunks.append(cur)
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--chunk-chars", type=int, default=0,
                    help="if >0, also emit chunks no larger than this many chars")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ext = os.path.splitext(args.file)[1].lower()
    dispatch = {".docx": extract_docx, ".epub": extract_epub,
                ".pdf": extract_pdf, ".txt": extract_txt}
    if ext not in dispatch:
        sys.exit(f"Unsupported format: {ext}. Supported: {', '.join(dispatch)}")
    if not os.path.exists(args.file):
        sys.exit(f"File not found: {args.file}")

    try:
        blocks = dispatch[ext](args.file)
    except Exception as e:  # noqa: BLE001 - report cleanly to the orchestrator
        sys.exit(f"EXTRACTION_ERROR ({ext}): {type(e).__name__}: {e}")

    if not blocks:
        sys.exit("EXTRACTION_EMPTY: no text recovered "
                 "(scanned PDF needing OCR? DRM-protected EPUB?)")

    title = next((b["text"] for b in blocks if b["type"] == "heading"),
                 os.path.splitext(os.path.basename(args.file))[0])
    result = {
        "source": os.path.abspath(args.file),
        "title": title,
        "char_count": sum(len(b["text"]) for b in blocks),
        "blocks": blocks,
    }
    if args.chunk_chars > 0:
        result["chunks"] = chunk_blocks(blocks, args.chunk_chars)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Wrote {args.out}: {len(blocks)} blocks, {result['char_count']} chars"
              + (f", {len(result['chunks'])} chunks" if args.chunk_chars else ""))
    else:
        print(payload)


if __name__ == "__main__":
    main()
