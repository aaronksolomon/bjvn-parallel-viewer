from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET


# ---------- Data structures ----------

@dataclass
class Span:
    aid: str
    page: int
    vi: str
    en: str

@dataclass
class Section:
    sid: str
    title_vi: str
    title_en: str
    spans: List[Span]

@dataclass
class Bundle:
    doc_id: str
    title: str
    pages: List[Dict[str, Any]]
    sections: List[Section]


# ---------- Utilities ----------

_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")

def _norm(s: str) -> str:
    """Normalize whitespace (preserve single newlines within paragraphs)."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _MULTI_NEWLINE_RE.sub("\n\n", s.strip())
    # collapse runs of spaces/tabs inside lines
    lines = [ _WHITESPACE_RE.sub(" ", ln).strip() for ln in s.split("\n") ]
    return "\n".join(lines).strip()

def _text_of(elem: ET.Element) -> str:
    return _norm("".join(elem.itertext()))


def _extract_digits(s: str) -> Optional[int]:
    m = re.search(r"(\d+)", s)
    return int(m[1]) if m else None

def _text_with_breaks(elem: ET.Element) -> str:
    """
    Extract text from an XML element, preserving <br/> as newline.
    """
    parts: List[str] = []

    def rec(e: ET.Element):
        if e.text:
            parts.append(e.text)
        for ch in list(e):
            if (ch.tag or "").lower() == "br":
                parts.append("\n")
                if ch.tail:
                    parts.append(ch.tail)
                continue
            rec(ch)
            if ch.tail:
                parts.append(ch.tail)

    rec(elem)
    return _norm("".join(parts))

# ---------- Image helpers ----------

def _iter_unannotated_images(images_dir: Path) -> List[Path]:
    """
    Return image files that contain 'unannotated_page' in the filename
    (case-insensitive) and have a common image extension.
    """
    exts = {".png", ".jpg", ".jpeg"}
    return sorted(
        p for p in images_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in exts
        and "unannotated_page" in p.name.lower()
    )

# ---------- Vietnamese OCR parsing (pagebreak format, verbatim text preservation) ----------

def parse_vi_ocr_xml(xml_path: Path) -> Dict[int, str]:
    """
    Parse Vietnamese OCR assuming a single format using <pagebreak page='X'/>.
    Returns a dict: {page_number: raw_text_preserving_newlines}.
    We DO NOT split into paragraphs; we preserve newlines and blank lines as-is.
    """
    root = ET.parse(xml_path).getroot()
    current_page = 1
    buckets: Dict[int, List[str]] = {}

    def push(text: str):
        nonlocal current_page
        if not text:
            return
        buckets.setdefault(current_page, []).append(text)

    # Collect text chunks in document order
    for node in root.iter():
        tag = (node.tag or '').lower()
        if tag == 'pagebreak':
            # switch page
            page_attr = node.attrib.get('page', '')
            num = _extract_digits(page_attr)
            if num is not None:
                current_page = num
            continue
        # Accumulate all textual content except pagebreak markers
        txt = ''.join(node.itertext()) if node is not root else (node.text or '')
        txt = txt or ''
        # Preserve original newlines; but normalize trailing spaces
        if txt.strip():
            push(txt)

    # Join buckets preserving blank lines
    vi_by_page: Dict[int, str] = {
        pg: '\n'.join(chunks) for pg, chunks in buckets.items()
    }
    return vi_by_page


# ---------- English translation parsing (aggregate text per page) ----------

def parse_en_translation_xml(xml_path: Path) -> Tuple[Dict[int, str], Optional[str]]:
    """
    Parse English translation and aggregate text *per page*, honoring <pagebreak page='X'/>.
    Handles pagebreaks inside or outside <section>, collects <notes> and <translation-notes>
    following a section, and preserves <br/> as newlines.

    Returns:
        (en_by_page: {page: text}, doc_title: Optional[str])
    """
    root = ET.parse(xml_path).getroot()

    en_buckets: Dict[int, List[str]] = {}
    current_page: int = 1
    doc_title: Optional[str] = None

    def push(pg: int, text: str) -> None:
        if text.strip():
            en_buckets.setdefault(pg, []).append(text.strip())

    def maybe_set_title(title_text: str) -> None:
        nonlocal doc_title
        t = (title_text or "").strip()
        if not t:
            return
        # Avoid 'Table of contents' as journal title
        if t.lower() in {"table of contents", "table of content", "contents"}:
            return
        if doc_title is None:
            doc_title = t

    def page_from_attr(e: ET.Element) -> Optional[int]:
        return _extract_digits(e.attrib.get("page", ""))

    def collect_section(sec: ET.Element) -> None:
        """
        Process a <section>, respecting internal <pagebreak/> and adding its text to current_page.
        """
        nonlocal current_page
        # Title (if present)
        title_el = sec.find("./title")
        if title_el is not None:
            maybe_set_title(_text_with_breaks(title_el))

        # Stream through children in order; flip page when we see <pagebreak/>
        for child in list(sec):
            tag = (child.tag or "").lower()
            if tag == "pagebreak":
                num = page_from_attr(child)
                if num is not None:
                    current_page = num
                continue
            if tag == "p":
                push(current_page, _text_with_breaks(child))
            elif tag in {"ul", "ol"}:
                # Flatten lists into lines
                items = []
                for li in child.findall("./li"):
                    items.append(_text_with_breaks(li))
                if items:
                    push(current_page, "\n".join(items))
            elif tag == "title":
                # already handled, but if there is trailing text in title, keep it
                pass
            else:
                # Any other container: extract text conservatively
                txt = _text_with_breaks(child)
                if txt.strip():
                    push(current_page, txt)

    # We want to honor pagebreaks that can appear between sections too. Iterate top-level in order.
    for node in list(root):
        tag = (node.tag or "").lower()

        if tag == "pagebreak":
            num = page_from_attr(node)
            if num is not None:
                current_page = num
            continue

        if tag == "section":
            collect_section(node)
            continue

        if tag in {"notes", "translation-notes"}:
            # Attach notes to the most recent page we’re on.
            # If notes contain multiple paragraphs, keep paragraph breaks.
            paras = [ _text_with_breaks(p) for p in node.findall("./p") ]
            if not paras:
                # Sometimes notes are raw text
                txt = _text_with_breaks(node)
                if txt.strip():
                    paras = [txt]
            if paras:
                header = "Notes" if tag == "notes" else "Translation notes"
                push(current_page, f"{header}:\n" + "\n\n".join(paras))
            continue

        # Any other unexpected top-level node: if it contains pagebreaks or text, handle best-effort
        inner_breaks = node.findall(".//pagebreak")
        if inner_breaks:
            # Walk depth-first and simulate what collect_section does
            for sub in node.iter():
                stag = (sub.tag or "").lower()
                if stag == "pagebreak":
                    num = page_from_attr(sub)
                    if num is not None:
                        current_page = num
                elif stag == "p":
                    push(current_page, _text_with_breaks(sub))
        else:
            # Plain text blob
            txt = _text_with_breaks(node)
            if txt.strip():
                push(current_page, txt)

    en_by_page: Dict[int, str] = {pg: "\n\n".join(chunks) for pg, chunks in en_buckets.items()}
    return en_by_page, doc_title


# ---------- Alignment & bundle building (page-level only) ----------

def align_and_build(
    doc_id: str,
    images_dir: Path,
    vi_by_page: Dict[int, str],
    en_by_page: Dict[int, str],
    fallback_title: Optional[str] = None
) -> Bundle:
    """
    Page-level alignment only: one span per page. We preserve text verbatim.
    AIDs are stable and page-scoped: {doc_id}:pg:{page}.
    Single section (s1) to keep the contract simple until finer alignment exists.
    """
    # Build page list from images (only use unannotated)
    pages: List[Dict[str, Any]] = []
    page_candidates: List[Path] = _iter_unannotated_images(images_dir)
    for img in page_candidates:
        num = _extract_digits(img.stem) or _extract_digits(img.name) or 0
        if num == 0:
            num = len(pages) + 1
        pages.append({"page": num, "image": f"/images/{img.name}"})

    # Union of all pages appearing in either stream (or in images as context)
    page_set = set(vi_by_page.keys()) | set(en_by_page.keys())
    if not page_set and pages:
        page_set = {p['page'] for p in pages}
    ordered_pages = sorted(page_set)

    spans: List[Span] = []
    spans.extend(
        Span(
            aid=f"{doc_id}:pg:{pg}",
            page=pg,
            vi=vi_by_page.get(pg, ""),
            en=en_by_page.get(pg, ""),
        )
        for pg in ordered_pages
    )
    section = Section(sid="s1", title_vi="", title_en="", spans=spans)
    title = fallback_title or doc_id.replace('-', ' ').title()
    return Bundle(doc_id=doc_id, title=title, pages=pages, sections=[section])


# ---------- Validation ----------

@dataclass
class ValidationIssue:
    level: str  # "ERROR" | "WARN" | "INFO"
    code: str
    message: str

def validate_bundle(bundle: Bundle, images_dir: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # Check unique aids
    seen: set[str] = set()
    for sec in bundle.sections:
        for sp in sec.spans:
            if sp.aid in seen:
                issues.append(ValidationIssue("ERROR", "DUP_AID", f"Duplicate aid: {sp.aid}"))
            seen.add(sp.aid)

    # Check page numbers present and corresponding images exist (best-effort)
    img_index: Dict[int, List[Path]] = {}
    for p in _iter_unannotated_images(images_dir):
        num = _extract_digits(p.stem) or _extract_digits(p.name)
        if num is not None:
            img_index.setdefault(num, []).append(p)

    referenced_pages = {sp.page for sec in bundle.sections for sp in sec.spans}
    issues.extend(
        ValidationIssue(
            "WARN", "MISSING_IMAGE", f"No image found for page {num}"
        )
        for num in sorted(referenced_pages)
        if num not in img_index
    )
    # Check empty texts
    for sec in bundle.sections:
        for sp in sec.spans:
            if not sp.vi.strip():
                issues.append(ValidationIssue("WARN", "EMPTY_VI", f"{sp.aid} has empty Vietnamese text"))
            if not sp.en.strip():
                issues.append(ValidationIssue("WARN", "EMPTY_EN", f"{sp.aid} has empty English text"))

    # Warn if a page has only one side populated
    for sec in bundle.sections:
        for sp in sec.spans:
            if not sp.vi.strip() and sp.en.strip():
                issues.append(ValidationIssue("INFO", "VI_MISSING_ON_PAGE", f"VI empty on page {sp.page}"))
            if sp.vi.strip() and not sp.en.strip():
                issues.append(ValidationIssue("INFO", "EN_MISSING_ON_PAGE", f"EN empty on page {sp.page}"))

    return issues

def iter_spans_text(bundle: Bundle, lang: str):
    for sec in bundle.sections:
        for sp in sec.spans:
            yield sp.vi if lang == "vi" else sp.en


# ---------- I/O ----------

def bundle_to_dict(bundle: Bundle) -> Dict[str, Any]:
    return {
        "doc_id": bundle.doc_id,
        "title": bundle.title,
        "pages": bundle.pages,
        "sections": [
            {
                "sid": sec.sid,
                "title_vi": sec.title_vi,
                "title_en": sec.title_en,
                "spans": [asdict(sp) for sp in sec.spans],
            } for sec in bundle.sections
        ],
    }


def write_bundle_json(bundle: Bundle, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle_to_dict(bundle), ensure_ascii=False, indent=2))


# ---------- Discovery ----------

def find_journal_inputs(journal_dir: Path) -> Tuple[Path, Path, Path]:
    """
    Discover the expected input files and images directory in a journal folder.

    Returns:
        (vi_xml_path, en_xml_path, images_dir)

    Raises:
        FileNotFoundError if any expected item is missing.
    """
    if not journal_dir.exists():
        raise FileNotFoundError(f"{journal_dir} not found")

    vi_xml = next(iter(journal_dir.glob("full_cleaned_*.xml")), None)
    en_xml = next(iter(journal_dir.glob("translation_*.xml")), None)
    images_dir = journal_dir / "images"

    if not vi_xml:
        raise FileNotFoundError("Vietnamese OCR XML not found (expected full_cleaned_*.xml)")
    if not en_xml:
        raise FileNotFoundError("English translation XML not found (expected translation_*.xml)")
    if not images_dir.exists():
        raise FileNotFoundError("images/ directory not found")

    return vi_xml, en_xml, images_dir

# ---------- Orchestration ----------

def build_from_journal_dir(journal_dir: Path, out_dir: Path) -> Tuple[Optional[Bundle], List[ValidationIssue]]:
    """
    Given a journal directory containing:
      - full_cleaned_<title>.xml   (Vietnamese OCR, pagebreak format)
      - translation_<title>.xml    (English translation, aggregated per page)
      - images/                    (page scans as PNG/JPG)
    Returns the built bundle and validation issues.
    """
    if not journal_dir.exists():
        raise FileNotFoundError(f"{journal_dir} not found")

    # Detect title token from directory name
    doc_id = journal_dir.name

    # Find files
    vi_xml, en_xml, images_dir = find_journal_inputs(journal_dir)

    # Parse
    vi_by_page = parse_vi_ocr_xml(vi_xml)
    en_by_page, en_title = parse_en_translation_xml(en_xml)

    # Build bundle
    bundle = align_and_build(
        doc_id=doc_id,
        images_dir=images_dir,
        vi_by_page=vi_by_page,
        en_by_page=en_by_page,
        fallback_title=en_title or doc_id.replace("-", " ").title(),
    )

    # Validate
    issues = validate_bundle(bundle, images_dir=images_dir)
    # Write
    out_path = out_dir / f"{doc_id}.json"
    write_bundle_json(bundle, out_path)
    return bundle, issues


def main(argv: Optional[List[str]] = None) -> int:
    # sourcery skip: use-fstring-for-concatenation
    parser = argparse.ArgumentParser(description="Build JVB JSON bundles from OCR + translation XML")
    parser.add_argument("journal_dirs", nargs="+", type=Path,
                        help="One or more journal directories, each containing full_cleaned_*.xml, translation_*.xml, and images/")
    parser.add_argument("--out", type=Path, default=Path("data"),
                        help="Output directory for bundle JSON (default: ./data)")
    parser.add_argument("--report", action="store_true",
                        help="Print validation issues report to stderr")
    args = parser.parse_args(argv)

    exit_code = 0
    for jd in args.journal_dirs:
        try:
            bundle, issues = build_from_journal_dir(jd, args.out)
            assert bundle
            print(f"[OK] {bundle.doc_id} → {args.out / (bundle.doc_id + '.json')}")
            if args.report and issues:
                for it in issues:
                    print(f" - {it.level}: {it.code}: {it.message}", file=sys.stderr)
            # Promote ERROR to non-zero exit
            if any(it.level == "ERROR" for it in issues):
                exit_code = 2
        except Exception as e:
            print(f"[FAIL] {jd}: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
