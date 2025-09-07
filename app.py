from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DATA_DIR: Path = Path("data")
IMAGES_DIR: Path = Path("images")

app: FastAPI = FastAPI()
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
app.mount("/static", StaticFiles(directory="templates"), name="static")  # optional
templates: Jinja2Templates = Jinja2Templates(directory="templates")


def _load_bundles() -> List[Dict[str, Any]]:
    """Load all bundle JSON files from DATA_DIR."""
    return [json.loads(p.read_text()) for p in sorted(DATA_DIR.glob("*.json"))]


def _get_bundle(doc_id: str) -> Optional[Dict[str, Any]]:
    for p in DATA_DIR.glob("*.json"):
        b: Dict[str, Any] = json.loads(p.read_text())
        if b.get("doc_id") == doc_id:
            return b
    return None


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    bundles: List[Dict[str, Any]] = _load_bundles()
    docs: List[Dict[str, str]] = [{"id": b["doc_id"], "title": b.get("title", b["doc_id"])} for b in bundles]
    return templates.TemplateResponse("index.html", {"request": request, "docs": docs})


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def view_doc(doc_id: str, request: Request) -> HTMLResponse:
    bundle: Optional[Dict[str, Any]] = _get_bundle(doc_id)
    if bundle is None:
        return templates.TemplateResponse("index.html", {"request": request, "docs": []})

    # Flatten spans and enrich with section context + alignment hints
    spans: List[Dict[str, Any]] = []
    sid_to_titles: Dict[str, Tuple[str, str]] = {}
    for section in bundle.get("sections", []):
        sid: str = section.get("sid", "")
        sid_to_titles[sid] = (section.get("title_vi", ""), section.get("title_en", ""))
        for sp in section.get("spans", []):
            sp2 = dict(sp)
            sp2["_section_sid"] = sid
            tvi, ten = sid_to_titles[sid]
            sp2["_section_title_vi"] = tvi
            sp2["_section_title_en"] = ten
            align = sp2.get("align") or {}
            sp2["_align_status"] = align.get("status")
            sp2["_align_method"] = align.get("method")
            spans.append(sp2)

    # Sort by page number for robust rendering
    spans.sort(key=lambda s: int(s.get("page", 10**9)))

    # Derive a safe first page from bundle pages
    first_page: int = 1
    if bundle.get("pages"):
        try:
            first_page = int(sorted(bundle["pages"], key=lambda p: int(p.get("page", 10**9)))[0]["page"])
        except Exception:
            first_page = 1

    return templates.TemplateResponse(
        "doc.html",
        {
            "request": request,
            "bundle": bundle,
            "spans": spans,
            "first_page": first_page,
        },
    )


@app.get("/api/doc/{doc_id}.json", response_class=JSONResponse)
def api_doc(doc_id: str) -> JSONResponse:
    bundle = _get_bundle(doc_id)
    if bundle:
        return JSONResponse(bundle)
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/doc/{doc_id}/page/{page}", response_class=JSONResponse)
def api_doc_page(doc_id: str, page: int) -> JSONResponse:
    """
    Resolve image source for a given doc_id+page using the bundle's 'pages' array
    as the source of truth (supports .png/.jpg/.jpeg and arbitrary filenames).
    """
    bundle = _get_bundle(doc_id)
    if not bundle:
        return JSONResponse({"error": "not found"}, status_code=404)
    pages: List[Dict[str, Any]] = bundle.get("pages", [])
    for p in pages:
        try:
            if int(p.get("page", -1)) == page:
                src = p.get("image") or p.get("src") or ""
                return JSONResponse({"page": page, "src": src})
        except Exception:
            continue
    if pages:
        p0 = sorted(pages, key=lambda x: int(x.get("page", 10**9)))[0]
        return JSONResponse({"page": int(p0.get("page", 1)), "src": p0.get("image") or p0.get("src") or ""})
    return JSONResponse({"page": 1, "src": ""})
