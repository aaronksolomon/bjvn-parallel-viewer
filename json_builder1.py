"""
json_builder — Two-AID bundle builder for JVB parallel viewer
=================================================================

Overview
--------
This module builds a *bundle JSON* used by the parallel viewer for the
"Journal of Vietnamese Buddhism" (and siblings). It normalizes inputs from:

1) Vietnamese OCR (page-scoped, `<pagebreak page='X'/>`)
2) English translation (section-scoped; may contain page markers; may *miss* some)
3) Page images (scans)
4) Optional section metadata (a.k.a. "sections.json" with title + start/end pages)

The bundle is designed around *two interoperable AID layers*:

- **Section AID (sAID)** — the *gold* logical unit for translation & processing.
- **Page AID (pAID)** — the physical unit aligned to scanned images.

This separation lets the system keep translations intact at the section level while
still enabling page-aligned viewing and interactive pagination repair when page
markers are missing in the EN translation.

Inputs (expected)
-----------------
- Vietnamese OCR XML:   `full_cleaned_*.xml`
  - Uses `<pagebreak page='X'/>` to indicate physical pages.
  - We preserve raw text with newlines (no paragraph inference).

- English translation XML: `translation_*.xml`
  - Contains `<section>` blocks with titles (vi/en) and body.
  - May contain `<pagebreak page='X'/>` *inside sections* (not guaranteed).
  - May contain `<notes>` and/or `<translation-notes>`.

- Page images: `images/unannotated_page_<N>.{png,jpg,jpeg}`
  - Filenames include page number `N`.

- Optional section metadata JSON: `sections.json` or `sections_meta.json`
  - Shape example (truncated):
    {
      "sections": [
        {
          "title_vi": "...",
          "title_en": "...",
          "start_page": 6,
          "end_page": 10,
          ...
        },
        ...
      ]
    }
  - When present, this is the **gold** source for section→page mapping.

AID Specification
-----------------
We generate opaque, stable IDs for cross-referencing:

- **Section AID (sAID):** `s:{doc_id}:{slug}`
  - `doc_id` is the journal directory name.
  - `slug` is a lowercase URL-like slug from the EN title (fallback to a 2-digit index).

- **Page AID (pAID):** `p:{doc_id}:{page}`
  - `page` is an integer page number (1-based).

These IDs are *opaque and immutable*. Tools should not parse them for meaning.
If you need new addressing schemes (e.g., paragraph IDs), *add* new AIDs – do not
repurpose existing ones.

Top-Level Bundle (Python dataclasses)
------------------------------------
- `Bundle`
  - `doc_id: str` — e.g., "jvb-1956-v3"
  - `title: str`  — human-friendly title (derived from EN title or doc_id)
  - `pages: List[{"page": int, "image": str}]` — discovered images (for viewer)
  - `sections: List[Section]` — each with page-level spans (below)
  - `annotations: Dict[AID, {"notes": [...], "translation_notes": [...]}] | None`
  - `aid_index: {"section_to_pages": Dict[sAID, List[int]], "page_to_section": Dict[str,int]} | None`
  - `section_blocks: List[SectionBlock] | None` — sAID-scoped EN blocks with pagination status & breaks
  - `edits: List[Edit] | None` — append-only reconciliation log (future UI)

- `Section`
  - `sid: str` — sAID
  - `title_vi: str`
  - `title_en: str`
  - `spans: List[Span]` — all page spans (pAIDs) belonging to this section.

- `Span`
  - `aid: str` — pAID
  - `page: int`
  - `vi: str` — VI text extracted for this page (raw, newline-preserving)
  - `en: str` — EN text *for this page*; may be empty if missing markers
  - `align: SpanAlign | None`
    - `status: "exact" | "inferred" | "pending"`
      - "pending": EN missing for this page; section contains the text
      - "inferred": a heuristic split was applied (see `method`)
      - "exact": page EN text is known to be correct and final
    - `method: Optional[str]` — "human", "vi_proportional", "uniform", etc.
    - `source: Optional[str]` — "section", "page", etc.

- `SectionBlock`
  - `aid: str` — sAID
  - `en: str`  — full EN text for the section (as provided by translation)
  - `vi: str`  — optional consolidated VI for the section (currently empty)
  - `pagination: Dict[str, Any]`
    - `target_pages: List[int]` — physical pages for this section (gold scope)
    - `status: "exact" | "incomplete" | "pending"`
      - "incomplete": target_pages known but page breaks missing in EN
      - "pending": no target_pages known (rare if sections.json absent)
    - `breaks: List[int]`
      - token indices in `en` where page breaks (end of page) occur
      - used to slice `en` into per-page pieces deterministically
    - `method: Optional[str]` — "human", "vi_proportional", "uniform", etc.

- `SpanAlign` — alignment hint for viewers/reconcilers (see above)

- `ValidationIssue`
  - `level: "ERROR" | "WARN" | "INFO"`
  - `code: str` — machine-readable issue code
  - `message: str` — human message

JSON Shape (bundle_to_dict)
---------------------------
The exported JSON mirrors the dataclasses above (with `align` serialized inline).
Field names are stable. Example (highly truncated):

{
  "doc_id": "jvb-1956-v3",
  "title": "Journal of Vietnamese Buddhism — 1956, Vol 3",
  "pages": [
    {"page": 1, "image": "/images/unannotated_page_1.png"},
    ...
  ],
  "sections": [
    {
      "sid": "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy",
      "title_vi": "Phật giáo với tinh thần dân chủ",
      "title_en": "Buddhism and the Spirit of Democracy",
      "spans": [
        {
          "aid": "p:jvb-1956-v3:6",
          "page": 6,
          "vi": "…",
          "en": "",
          "align": {"status": "pending", "method": null, "source": "section"}
        },
        ...
      ]
    },
    ...
  ],
  "annotations": {
    "p:jvb-1956-v3:6": {"notes": ["…"], "translation_notes": ["…"]},
    "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy": {}
  },
  "aid_index": {
    "section_to_pages": {
      "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy": [6,7,8,9,10]
    },
    "page_to_section": {
      "6": "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy",
      "7": "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy"
    }
  },
  "section_blocks": [
    {
      "aid": "s:jvb-1956-v3:04-buddhism-and-the-spirit-of-democracy",
      "en": "…full section EN…",
      "vi": "",
      "pagination": {
        "target_pages": [6,7,8,9,10],
        "status": "incomplete",
        "breaks": [],
        "method": null
      }
    }
  ],
  "edits": []
}

Intended Use (typical flows)
----------------------------
**Build time (this module)**
1. Parse VI OCR → `vi_by_page[page] = raw text`
2. Parse EN translation:
   - Aggregate EN per page when `<pagebreak/>` exists → `en_by_page[page]`
   - Capture full section EN blobs → `section_en_by_sid[sAID]`
   - Collect notes & translation-notes by *current page* (sidecar)
3. Determine section↔page index:
   - Prefer `sections.json` (gold), else infer from EN `<section>` + `<pagebreak/>`
4. Emit:
   - Page-level `Span`s (may have empty EN where missing)
   - `SectionBlock`s (with `status` & `target_pages`)
   - `annotations` sidecar keyed by AID
   - `aid_index` for routing (section→pages, page→section)
   - `edits` (empty; reserved for reconciliation UI)
5. Validate and report issues (missing images, empty texts, missing pagebreaks).

**Viewer: pagination repair (human-in-the-loop)**
1. Load a `SectionBlock` (sAID) and associated `target_pages` (page images).
2. Render full `en` body with a token (or sentence) ruler.
3. Human inserts pagebreaks → produce `breaks` array (end token indices).
4. Write an `edits` entry (append-only) with `op="insert_pagebreak"`, `after_token`, `page`.
5. Reconciler applies edits:
   - Set `pagination.status="exact"`, `method="human"`.
   - Slice section EN into page pieces and populate `Span.en` for each target page.
   - Set `Span.align.status="exact"` (or keep `"inferred"` if a heuristic proposal is accepted).

**Heuristic proposal (optional)**
- Provide an automatic suggestion using VI-length proportional splitting:
  - Compute weights from VI char counts per page.
  - Split EN tokens proportionally; snap to nearest sentence boundaries.
  - Mark `pagination.status="incomplete"`, `method="vi_proportional"`, and set `Span.align.status="inferred"`.
  - Human can accept → flip to `"exact"` + `method="human"`, or adjust.

Validation Signals (selected)
-----------------------------
- `ERROR DUP_AID`: duplicate page AID (should never happen).
- `WARN MISSING_IMAGE`: no image for a referenced page.
- `WARN EMPTY_VI` / `WARN EMPTY_EN`: empty text in a page span.
- `INFO EN_PENDING_FROM_SECTION`: page EN is empty but the section has content (repairable).
- `WARN MISSING_PAGEBREAKS`: section has target pages but EN lacks per-page breaks.
- `INFO SECTION_PAGINATION_PENDING`: section has no target pages (rare; implies weak metadata).

Notes & Translation-Notes
-------------------------
- Stored in `annotations` sidecar keyed by AID.
- Parser currently attaches them to *page AIDs* based on the page context while parsing.
- Tools may choose to "lift" or mirror these annotations to the section AID to reflect logical scope.

Extensibility Roadmap
---------------------
- **Paragraph / Sentence AIDs:** introduce `para:{doc_id}:{sSlug}:{k}` or `sent:{...}` and a
  new index `paragraph_to_pages`, `sentence_to_page`. Do *not* overload sAID/pAID.
- **Per-page provenance:** if EN slices were reconciled by human or heuristic, mark both at
  the SectionBlock level (`pagination.method`) and the Span level (`align.method`).
- **Rich metadata:** carry `author`, `keywords`, etc. from `sections.json` into `Section`.
- **Bidirectional notes:** allow `annotations` at both sAID and pAID; viewers can inherit
  section notes down to pages when rendering (without duplicating storage).

Design Choices
--------------
- **Two AIDs** keep processing (section) clean and viewing (page) flexible.
- **Sidecars** avoid polluting text content with inline note markers while preserving structure.
- **Index** enables fast, unambiguous routing between logical and physical views.
- **Edits log** makes reconciliation auditable and reversible.
- **Opaque IDs** allow future refactors without breaking consumers.

Backwards Compatibility
-----------------------
This prototype does not aim for backwards compatibility with earlier bundles.
Downstream tools should consume the shapes described here.

CLI
---
Usage:
    python json_builder1.py <journal_dir> [<journal_dir> ...] --out ./data --report

Outputs `<doc_id>.json` in the output directory and optionally prints a validation report.

Glossary
--------
- **AID** — Addressable ID; an opaque, stable identifier used for cross-references.
- **sAID** — Section AID (`s:<doc_id>:<slug>`).
- **pAID** — Page AID (`p:<doc_id>:<page>`).
- **SectionBlock** — Section-scoped container for EN text + pagination state.
- **Span** — Page-scoped text container for VI/EN with alignment hints.
- **Reconciliation** — The process of transforming section EN into per-page EN via
  human edits or heuristics, producing `breaks` and updating `Span.en`.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Iterable
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET



# ========== Data structures ==========

# ---- Low-level primitives ----

@dataclass
class SpanAlign:
    status: str  # "exact" | "inferred" | "pending"
    method: Optional[str] = None  # e.g., "human", "vi_proportional", "uniform", None
    source: Optional[str] = None  # e.g., "section", "page"

@dataclass
class Span:
    aid: str             # page-level AID: p:{doc_id}:{page}
    page: int
    vi: str
    en: str
    align: Optional[SpanAlign] = None

@dataclass
class Section:
    sid: str             # logical section AID: s:{doc_id}:{slug-or-index}
    title_vi: str
    title_en: str
    spans: List[Span]    # page-level spans that belong to the section (may have empty EN if unknown)

@dataclass
class SectionBlock:
    """
    Section-level text container with pagination status/breaks.
    This is the 'gold' translation scope feeding page-level reconciliation.
    """
    aid: str
    en: str
    vi: str
    pagination: Dict[str, Any]  # {target_pages: [...], status, breaks: [int], method}

@dataclass
class ValidationIssue:
    level: str  # "ERROR" | "WARN" | "INFO"
    code: str
    message: str

# ---- Aggregates ----

@dataclass
class Bundle:
    doc_id: str
    title: str
    pages: List[Dict[str, Any]]     # [{page, image}]
    sections: List[Section]

    # ---- New optional, additive fields ----
    # AID-addressable annotations (notes and translation_notes)
    # { "<AID>": { "notes": [...], "translation_notes": [...] } }
    annotations: Optional[Dict[str, Dict[str, List[str]]]] = None

    # Section↔Page index for routing
    # {
    #   "section_to_pages": { "<section_aid>": [6,7,8,9,10], ... },
    #   "page_to_section": { "6": "<section_aid>", ... }
    # }
    aid_index: Optional[Dict[str, Any]] = None

    # Gold section blocks with pagination metadata
    section_blocks: Optional[List[SectionBlock]] = None

    # Append-only edits log (future reconciliation UI)
    # [{op: "insert_pagebreak", section_aid, after_token, page, ts, user}, ...]
    edits: Optional[List[Dict[str, Any]]] = None
    
@dataclass
class EnParseResult:
    en_by_page: Dict[int, str]
    doc_title: Optional[str]
    # AID-addressable notes sidecars (we'll attach sAIDs during build)
    notes_by_page: Dict[int, List[str]]
    trnotes_by_page: Dict[int, List[str]]
    # Section capture
    section_en_by_sid: Dict[str, str]                # sid -> full EN text (contiguous as given)
    section_pages_observed: Dict[str, List[int]]     # sid -> ordered pages observed inside that section
    section_titles: Dict[str, Tuple[str, str]]       # sid -> (title_vi, title_en)


# ========== Utilities ==========

_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
_NON_WORD_RE = re.compile(r"[^a-z0-9\-]+")

def _norm(s: str) -> str:
    """Normalize whitespace (preserve single newlines within paragraphs)."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _MULTI_NEWLINE_RE.sub("\n\n", s.strip())
    lines = [_WHITESPACE_RE.sub(" ", ln).strip() for ln in s.split("\n")]
    return "\n".join(lines).strip()

def _text_of(elem: ET.Element) -> str:
    return _norm("".join(elem.itertext()))

def _extract_digits(s: str) -> Optional[int]:
    # sourcery skip: use-getitem-for-re-match-groups
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None

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

def _slug(s: str, fallback: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return fallback
    s = s.replace("&", " and ")
    s = _NON_WORD_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or fallback


# ========== Image helpers ==========

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


# ========== Vietnamese OCR parsing (pagebreak format, verbatim text preservation) ==========

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

    for node in root.iter():
        tag = (node.tag or "").lower()
        if tag == "pagebreak":
            page_attr = node.attrib.get("page", "")
            num = _extract_digits(page_attr)
            if num is not None:
                current_page = num
            continue
        txt = "".join(node.itertext()) if node is not root else (node.text or "")
        txt = txt or ""
        if txt.strip():
            push(txt)

    vi_by_page: Dict[int, str] = {pg: "\n".join(chunks) for pg, chunks in buckets.items()}
    return vi_by_page


# ========== English parsing with section capture, notes sidecars, page aggregation ==========

def parse_en_translation_xml(doc_id: str, xml_path: Path) -> EnParseResult:
    """
    Parse English translation:

    - Aggregates text per page using <pagebreak page='X'/>.
    - Captures <section> text as section-level EN blobs.
    - Collects <notes> and <translation-notes> as page-scoped sidecars (for now; we reattach to sAID later).
    - Preserves <br/> as newlines.
    """
    root = ET.parse(xml_path).getroot()

    en_buckets: Dict[int, List[str]] = {}
    current_page: int = 1
    doc_title: Optional[str] = None

    notes_by_page: Dict[int, List[str]] = {}
    trnotes_by_page: Dict[int, List[str]] = {}

    section_en_by_sid: Dict[str, str] = {}
    section_pages_observed: Dict[str, List[int]] = {}
    section_titles: Dict[str, Tuple[str, str]] = {}

    section_counter = 0
    current_sid: Optional[str] = None
    current_section_chunks: List[str] = []

    # --------- Local helpers (IO-free, pure) ----------
    def push_page(pg: int, text: str) -> None:
        if text.strip():
            en_buckets.setdefault(pg, []).append(text.strip())

    def note_add(target: Dict[int, List[str]], pg: int, text: str) -> None:
        if text.strip():
            target.setdefault(pg, []).append(text.strip())

    def maybe_set_title(title_text: str) -> None:
        nonlocal doc_title
        t = (title_text or "").strip()
        if not t:
            return
        if t.lower() in {"table of contents", "table of content", "contents"}:
            return
        if doc_title is None:
            doc_title = t

    def page_from_attr(e: ET.Element) -> Optional[int]:
        return _extract_digits(e.attrib.get("page", ""))

    def _collect_list_text(list_el: ET.Element) -> str:
        items = [_text_with_breaks(li) for li in list_el.findall("./li")]
        return "\n".join([it for it in items if it.strip()])

    def _collect_notes_text(el: ET.Element) -> str:
        paras = [_text_with_breaks(p) for p in el.findall("./p")]
        if not paras:
            txt = _text_with_breaks(el)
            if txt.strip():
                paras = [txt]
        return "\n\n".join([p for p in paras if p.strip()])

    def _start_section(sec_el: ET.Element) -> str:
        nonlocal section_counter, current_sid, current_section_chunks
        section_counter += 1
        title_vi_el = sec_el.find("./title_vi")
        title_en_el = sec_el.find("./title") or sec_el.find("./title_en")
        title_vi = _text_with_breaks(title_vi_el) if title_vi_el is not None else ""
        title_en = _text_with_breaks(title_en_el) if title_en_el is not None else ""
        if title_en:
            maybe_set_title(title_en)
        slug = _slug(title_en or title_vi, fallback=f"{section_counter:02d}")
        sid = f"s:{doc_id}:{slug}"
        section_titles[sid] = (title_vi, title_en)
        current_sid = sid
        current_section_chunks = []
        section_pages_observed[sid] = []
        return sid

    def _end_section(sid: Optional[str]) -> None:
        nonlocal current_sid, current_section_chunks
        if sid is None:
            return
        section_en_by_sid[sid] = _norm("\n\n".join(current_section_chunks).strip())
        current_sid = None
        current_section_chunks = []

    # --------- Dispatchers ----------
    def _handle_section_child(child: ET.Element, sid: str) -> None:
        nonlocal current_page
        ctag = (child.tag or "").lower()
        match ctag:
            case "pagebreak":
                num = page_from_attr(child)
                if num is not None:
                    current_page = num
                    section_pages_observed[sid].append(num)
            case "p":
                txt = _text_with_breaks(child)
                if txt:
                    push_page(current_page, txt)
                    current_section_chunks.append(txt)
            case "ul" | "ol":
                txt = _collect_list_text(child)
                if txt:
                    push_page(current_page, txt)
                    current_section_chunks.append(txt)
            case "title" | "title_en" | "title_vi":
                # already processed at section start
                return
            case "notes":
                combined = _collect_notes_text(child)
                if combined:
                    note_add(notes_by_page, current_page, combined)
            case "translation-notes":
                combined = _collect_notes_text(child)
                if combined:
                    note_add(trnotes_by_page, current_page, combined)
            case _:
                txt = _text_with_breaks(child)
                if txt.strip():
                    push_page(current_page, txt)
                    current_section_chunks.append(txt)

    def _handle_top_level(node: ET.Element) -> None:
        nonlocal current_page
        tag = (node.tag or "").lower()
        match tag:
            case "pagebreak":
                num = page_from_attr(node)
                if num is not None:
                    current_page = num
            case "section":
                # Close any previous open section (defensive)
                _end_section(current_sid)
                sid = _start_section(node)
                for child in list(node):
                    _handle_section_child(child, sid)
                _end_section(sid)
            case "notes":
                combined = _collect_notes_text(node)
                if combined:
                    note_add(notes_by_page, current_page, combined)
            case "translation-notes":
                combined = _collect_notes_text(node)
                if combined:
                    note_add(trnotes_by_page, current_page, combined)
            case _:
                # Best-effort: if this node contains inner pagebreaks, walk in order
                inner_breaks = node.findall(".//pagebreak")
                if inner_breaks:
                    for sub in node.iter():
                        stag = (sub.tag or "").lower()
                        if stag == "pagebreak":
                            num = page_from_attr(sub)
                            if num is not None:
                                current_page = num
                        elif stag == "p":
                            push_page(current_page, _text_with_breaks(sub))
                else:
                    txt = _text_with_breaks(node)
                    if txt.strip():
                        push_page(current_page, txt)

    # --------- Stream the document ----------
    for node in list(root):
        _handle_top_level(node)

    en_by_page: Dict[int, str] = {pg: "\n\n".join(chunks) for pg, chunks in en_buckets.items()}

    return EnParseResult(
        en_by_page=en_by_page,
        doc_title=doc_title,
        notes_by_page=notes_by_page,
        trnotes_by_page=trnotes_by_page,
        section_en_by_sid=section_en_by_sid,
        section_pages_observed=section_pages_observed,
        section_titles=section_titles,
    )

# ========== Section metadata ingestion (optional) ==========

@dataclass
class SectionMeta:
    sid: str
    title_vi: str
    title_en: str
    start_page: int
    end_page: int

def _load_sections_json(doc_id: str, path: Path) -> Optional[List[SectionMeta]]:
    """
    If a section metadata file exists, load it.
    We synthesize sAIDs using a slug of the English title.
    """
    if not path.exists():
        return None
    obj = json.loads(path.read_text())
    items = obj.get("sections") or []
    metas: List[SectionMeta] = []
    for i, it in enumerate(items, start=1):
        title_en = (it.get("title_en") or "").strip()
        title_vi = (it.get("title_vi") or "").strip()
        slug = _slug(title_en or title_vi, fallback=f"{i:02d}")
        sid = f"s:{doc_id}:{slug}"
        sp = int(it.get("start_page"))
        ep = int(it.get("end_page"))
        metas.append(SectionMeta(sid=sid, title_vi=title_vi, title_en=title_en, start_page=sp, end_page=ep))
    return metas


# ========== Alignment & bundle building (two AIDs) ==========

import warnings

def _pages_from_images(images_dir: Path) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    used_numbers = set()
    fallback_counter = 1
    # Sort images by name to ensure deterministic ordering for fallback numbering
    images = sorted(_iter_unannotated_images(images_dir), key=lambda img: img.name)
    for img in images:
        num = _extract_digits(img.stem) or _extract_digits(img.name) or 0
        if num == 0:
            # Find the next available fallback number not already used
            while fallback_counter in used_numbers:
                fallback_counter += 1
            num = fallback_counter
            warnings.warn(
                f"Image '{img.name}' does not contain digits for page number. "
                f"Assigning fallback page number {num}."
            )
            fallback_counter += 1
        if num in used_numbers:
            warnings.warn(
                f"Duplicate page number {num} detected for image '{img.name}'."
            )
        used_numbers.add(num)
        pages.append({"page": num, "image": f"/images/{img.name}"})
    return pages

def _build_aid_index_from_meta(metas: List[SectionMeta]) -> Tuple[Dict[str, List[int]], Dict[str, str]]:
    section_to_pages: Dict[str, List[int]] = {}
    page_to_section: Dict[str, str] = {}
    for m in metas:
        rng = list(range(m.start_page, m.end_page + 1))
        section_to_pages[m.sid] = rng
        for p in rng:
            page_to_section[str(p)] = m.sid
    return section_to_pages, page_to_section

def _build_aid_index_from_en_observed(s_titles: Dict[str, Tuple[str, str]], s_pages: Dict[str, List[int]]) -> Tuple[Dict[str, List[int]], Dict[str, str]]:
    section_to_pages: Dict[str, List[int]] = {}
    page_to_section: Dict[str, str] = {}
    for sid, pages in s_pages.items():
        uniq = []
        seen = set()
        for p in pages:
            if p not in seen:
                uniq.append(p)
                seen.add(p)
        if uniq:
            section_to_pages[sid] = uniq
            for p in uniq:
                page_to_section[str(p)] = sid
    return section_to_pages, page_to_section

def _attach_annotations(
    annotations: Dict[str, Dict[str, List[str]]],
    aid: str,
    notes: List[str] | None,
    trnotes: List[str] | None,
) -> None:
    if not notes and not trnotes:
        return
    dest = annotations.setdefault(aid, {})
    if notes:
        dest.setdefault("notes", []).extend(notes)
    if trnotes:
        dest.setdefault("translation_notes", []).extend(trnotes)

def _compute_title(doc_id: str, parse_res: EnParseResult, fallback_title: Optional[str]) -> str:
    """
    Choose a human-friendly title:
    1) explicit fallback_title if provided,
    2) document title parsed from EN,
    3) title-cased doc_id.
    """
    return fallback_title or parse_res.doc_title or doc_id.replace("-", " ").title()

def _make_sections(
    doc_id: str,
    spans_by_page: Dict[int, Span],
    title_lookup: Dict[str, Tuple[str, str]],
    section_to_pages: Dict[str, List[int]],
) -> List[Section]:
    """
    Assemble Section objects in a predictable order using title_lookup keys.
    Each Section contains the Span objects for its pages (if present).
    """
    sections: List[Section] = []
    # Sort section ids by the first page number in section_to_pages, or float('inf') if no pages
    sorted_sids = sorted(
        title_lookup.keys(),
        key=lambda sid: section_to_pages.get(sid, [float('inf')])[0] if section_to_pages.get(sid) else float('inf')
    )
    for sid in sorted_sids:
        title_vi, title_en = title_lookup.get(sid, ("", ""))
        pg_list = section_to_pages.get(sid, [])
        sec_spans = [spans_by_page[p] for p in pg_list if p in spans_by_page]
        sections.append(Section(sid=sid, title_vi=title_vi, title_en=title_en, spans=sec_spans))
    return sections

def _make_section_blocks(
    section_order: List[str],
    section_to_pages: Dict[str, List[int]],
    parse_res: EnParseResult,
) -> List[SectionBlock]:
    """
    Build SectionBlock entries capturing the full EN text and pagination state.
    A section is 'exact' if all target pages have non-empty EN; 'incomplete' if
    there are target pages but some are missing EN; 'pending' if no targets.
    """
    section_blocks: List[SectionBlock] = []
    vi = ""
    for sid in section_order:
        en = parse_res.section_en_by_sid.get(sid, "")
        target_pages = section_to_pages.get(sid, [])
        all_have_en = all(parse_res.en_by_page.get(p, "").strip() for p in target_pages) if target_pages else False
        status = "exact" if (target_pages and all_have_en) else ("incomplete" if target_pages else "pending")
        pagination = {"target_pages": target_pages, "status": status, "breaks": [], "method": None}
        section_blocks.append(SectionBlock(aid=sid, en=en, vi=vi, pagination=pagination))
    return section_blocks

def _make_annotations(doc_id: str, section_order: List[str], parse_res: EnParseResult) -> Optional[Dict[str, Dict[str, List[str]]]]:
    """
    Construct the annotations sidecar keyed by AID. Page-scoped notes are attached to pAIDs.
    Empty dicts for section AIDs are created to simplify future edits.
    """
    annotations: Dict[str, Dict[str, List[str]]] = {}
    for pg, notes in parse_res.notes_by_page.items():
        _attach_annotations(annotations, f"p:{doc_id}:{pg}", notes, None)
    for pg, tnotes in parse_res.trnotes_by_page.items():
        _attach_annotations(annotations, f"p:{doc_id}:{pg}", None, tnotes)
    for sid in section_order:
        annotations.setdefault(sid, {})
    return annotations or None

def _make_aid_index(
    section_to_pages: Dict[str, List[int]],
    page_to_section: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """
    Package the routing indices into a stable dict shape or return None if empty.
    """
    if not section_to_pages:
        return None
    return {
        "section_to_pages": section_to_pages,
        "page_to_section": page_to_section,
    }

def build_bundle(
    doc_id: str,
    images_dir: Path,
    vi_by_page: Dict[int, str],
    parse_res: EnParseResult,
    sections_meta: Optional[List[SectionMeta]] = None,
    fallback_title: Optional[str] = None,
) -> Bundle:
    """
    Build a rich bundle with two AID layers and sidecars.
    """
    pages = _pages_from_images(images_dir)

    # SECTION↔PAGE INDEX (prefer external meta; else EN observed)
    if sections_meta:
        section_to_pages, page_to_section = _build_aid_index_from_meta(sections_meta)
        title_lookup = {m.sid: (m.title_vi, m.title_en) for m in sections_meta}
    else:
        section_to_pages, page_to_section = _build_aid_index_from_en_observed(
            parse_res.section_titles, parse_res.section_pages_observed
        )
        title_lookup = parse_res.section_titles

    # PAGE UNION
    page_set = set(vi_by_page.keys()) | set(parse_res.en_by_page.keys())
    if not page_set and pages:
        page_set = {p["page"] for p in pages}
    ordered_pages = sorted(page_set)

    # Human-friendly title
    title = _compute_title(doc_id, parse_res, fallback_title)

    # Build page-level Span objects
    spans_by_page: Dict[int, Span] = {}
    for pg in ordered_pages:
        en = parse_res.en_by_page.get(pg, "")
        vi = vi_by_page.get(pg, "")
        sid = page_to_section.get(str(pg))
        align = SpanAlign(status="pending", source="section") if (not en and sid) else None
        spans_by_page[pg] = Span(aid=f"p:{doc_id}:{pg}", page=pg, vi=vi, en=en, align=align)

    # Sections
    sections = _make_sections(doc_id, spans_by_page, title_lookup, section_to_pages)

    # Section blocks
    section_order = list(title_lookup.keys())
    section_blocks = _make_section_blocks(section_order, section_to_pages, parse_res) or None

    # Annotations sidecar
    annotations = _make_annotations(doc_id, section_order, parse_res)

    # Aid index
    aid_index = _make_aid_index(section_to_pages, page_to_section)

    return Bundle(
        doc_id=doc_id,
        title=title,
        pages=pages,
        sections=sections,
        annotations=annotations,
        aid_index=aid_index,
        section_blocks=section_blocks,
        edits=[],
    )


# ========== Validation ==========

def validate_bundle(bundle: Bundle, images_dir: Path) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    def _check_unique_aids() -> None:
        seen: set[str] = set()
        for sec in bundle.sections:
            for sp in sec.spans:
                if sp.aid in seen:
                    issues.append(ValidationIssue("ERROR", "DUP_AID", f"Duplicate aid: {sp.aid}"))
                seen.add(sp.aid)

    def _build_image_index() -> Dict[int, List[Path]]:
        idx: Dict[int, List[Path]] = {}
        for p in _iter_unannotated_images(images_dir):
            num = _extract_digits(p.stem) or _extract_digits(p.name)
            if num is not None:
                idx.setdefault(num, []).append(p)
        return idx

    def _check_images(img_index: Dict[int, List[Path]]) -> None:
        referenced_pages = {sp.page for sec in bundle.sections for sp in sec.spans}
        for num in sorted(referenced_pages):
            if num not in img_index:
                issues.append(ValidationIssue("WARN", "MISSING_IMAGE", f"No image found for page {num}"))

    def _check_texts_and_alignment() -> None:
        for sec in bundle.sections:
            for sp in sec.spans:
                if not sp.vi.strip():
                    issues.append(ValidationIssue("WARN", "EMPTY_VI", f"{sp.aid} has empty Vietnamese text"))
                if not sp.en.strip():
                    issues.append(ValidationIssue("WARN", "EMPTY_EN", f"{sp.aid} has empty English text"))
                if sp.align and sp.align.status == "pending":
                    issues.append(ValidationIssue("INFO", "EN_PENDING_FROM_SECTION", f"{sp.aid} EN pending; source=section"))

    def _check_section_blocks() -> None:
        if not bundle.section_blocks:
            return
        for sb in bundle.section_blocks:
            pagination = sb.pagination or {}
            status = pagination.get("status")
            tgt = pagination.get("target_pages") or []
            if status == "incomplete" and tgt:
                issues.append(ValidationIssue(
                    "WARN",
                    "MISSING_PAGEBREAKS",
                    f"Section {sb.aid} missing EN pagebreaks across pages {min(tgt)}-{max(tgt)}",
                ))
            if status == "pending":
                issues.append(ValidationIssue(
                    "INFO",
                    "SECTION_PAGINATION_PENDING",
                    f"Section {sb.aid} has no target pages",
                ))

    _check_unique_aids()
    img_index = _build_image_index()
    _check_images(img_index)
    _check_texts_and_alignment()
    _check_section_blocks()
    return issues

def iter_spans_text(bundle: Bundle, lang: str) -> Iterable[str]:
    for sec in bundle.sections:
        for sp in sec.spans:
            yield sp.vi if lang == "vi" else sp.en


# ========== I/O ==========

def _span_to_dict(sp: Span) -> Dict[str, Any]:
    """
    Serialize a Span to a plain dict, ensuring align is serialized (if present).
    """
    if sp.align is None:
        return asdict(sp)
    d = asdict(sp)
    d["align"] = asdict(sp.align)
    return d


def _section_to_dict(sec: Section) -> Dict[str, Any]:
    """
    Serialize a Section (with its Spans) to a plain dict.
    """
    return {
        "sid": sec.sid,
        "title_vi": sec.title_vi,
        "title_en": sec.title_en,
        "spans": [_span_to_dict(sp) for sp in sec.spans],
    }


def bundle_to_dict(bundle: Bundle) -> Dict[str, Any]:
    sections: List[Dict[str, Any]] = [_section_to_dict(sec) for sec in bundle.sections]

    section_blocks: Optional[List[Dict[str, Any]]] = [
        {
            "aid": sb.aid,
            "en": sb.en,
            "vi": sb.vi,
            "pagination": sb.pagination,
        }
        for sb in (bundle.section_blocks or [])
    ] or None

    return {
        "doc_id": bundle.doc_id,
        "title": bundle.title,
        "pages": bundle.pages,
        "sections": sections,
        "annotations": bundle.annotations,
        "aid_index": bundle.aid_index,
        "section_blocks": section_blocks,
        "edits": bundle.edits or None,
    }

def write_bundle_json(bundle: Bundle, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle_to_dict(bundle), ensure_ascii=False, indent=2))


# ========== Discovery ==========

def find_journal_inputs(journal_dir: Path) -> Tuple[Path, Path, Path, Optional[Path]]:
    """
    Discover expected input files and images directory in a journal folder.

    Returns:
        (vi_xml_path, en_xml_path, images_dir, sections_json_path | None)

    Raises:
        FileNotFoundError if any required item is missing (VI, EN, images).
    """
    if not journal_dir.exists():
        raise FileNotFoundError(f"{journal_dir} not found")

    vi_xml = next(iter(journal_dir.glob("full_cleaned_*.xml")), None)
    en_xml = next(iter(journal_dir.glob("translation_*.xml")), None)
    images_dir = journal_dir / "images"

    # Optional sections JSON; accept common names
    sections_json = None
    for candidate in ("sections.json", "section_metadata.json"):
        p = journal_dir / candidate
        if p.exists():
            sections_json = p
            break

    if not vi_xml:
        raise FileNotFoundError("Vietnamese OCR XML not found (expected full_cleaned_*.xml)")
    if not en_xml:
        raise FileNotFoundError("English translation XML not found (expected translation_*.xml)")
    if not images_dir.exists():
        raise FileNotFoundError("images/ directory not found")

    return vi_xml, en_xml, images_dir, sections_json


# ========== Orchestration ==========

def build_from_journal_dir(journal_dir: Path, out_dir: Path) -> Tuple[Optional[Bundle], List[ValidationIssue]]:
    """
    Given a journal directory containing:
      - full_cleaned_<title>.xml   (Vietnamese OCR, pagebreak format)
      - translation_<title>.xml    (English translation)
      - images/                    (page scans as PNG/JPG)
      - [optional] sections.json   (section metadata with start/end pages)
    Returns the built bundle and validation issues.
    """
    if not journal_dir.exists():
        raise FileNotFoundError(f"{journal_dir} not found")

    doc_id = journal_dir.name

    vi_xml, en_xml, images_dir, sections_json = find_journal_inputs(journal_dir)

    vi_by_page = parse_vi_ocr_xml(vi_xml)
    en_res = parse_en_translation_xml(doc_id=doc_id, xml_path=en_xml)

    metas = _load_sections_json(doc_id, sections_json) if sections_json else None

    bundle = build_bundle(
        doc_id=doc_id,
        images_dir=images_dir,
        vi_by_page=vi_by_page,
        parse_res=en_res,
        sections_meta=metas,
        fallback_title=en_res.doc_title or doc_id.replace("-", " ").title(),
    )

    issues = validate_bundle(bundle, images_dir=images_dir)

    out_path = out_dir / f"{doc_id}.json"
    write_bundle_json(bundle, out_path)
    return bundle, issues


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build JVB JSON bundles (two-AID, notes sidecars, section index)")
    parser.add_argument(
        "journal_dirs", nargs="+", type=Path,
        help="One or more journal directories with full_cleaned_*.xml, translation_*.xml, images/, and optional sections.json"
    )
    parser.add_argument("--out", type=Path, default=Path("data"), help="Output directory for bundle JSON (default: ./data)")
    parser.add_argument("--report", action="store_true", help="Print validation issues report to stderr")
    args = parser.parse_args(argv)

    exit_code = 0
    for jd in args.journal_dirs:
        try:
            bundle, issues = build_from_journal_dir(jd, args.out)
            assert bundle
            print(f"[OK] {bundle.doc_id} → {args.out / f'{bundle.doc_id}.json'}")
            if args.report and issues:
                for it in issues:
                    print(f" - {it.level}: {it.code}: {it.message}", file=sys.stderr)
            if any(it.level == "ERROR" for it in issues):
                exit_code = 2
        except (FileNotFoundError, ET.ParseError, AssertionError) as e:
            print(f"[FAIL] {jd}: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())