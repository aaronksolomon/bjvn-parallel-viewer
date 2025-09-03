from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
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
    bundles: List[Dict[str, Any]] = []
    for p in sorted(DATA_DIR.glob("*.json")):
        bundles.append(json.loads(p.read_text()))
    return bundles


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    bundles: List[Dict[str, Any]] = _load_bundles()
    docs: List[Dict[str, str]] = [{"id": b["doc_id"], "title": b.get("title", b["doc_id"])} for b in bundles]
    return templates.TemplateResponse("index.html", {"request": request, "docs": docs})


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def view_doc(doc_id: str, request: Request) -> HTMLResponse:
    bundle: Dict[str, Any] | None = None
    for b in _load_bundles():
        if b["doc_id"] == doc_id:
            bundle = b
            break
    if bundle is None:
        return templates.TemplateResponse("index.html", {"request": request, "docs": []})

    spans: List[Dict[str, Any]] = []
    for section in bundle.get("sections", []):
        spans.extend(section.get("spans", []))

    first_page: int = bundle["pages"][0]["page"] if bundle.get("pages") else 1
    return templates.TemplateResponse(
        "doc.html",
        {"request": request, "bundle": bundle, "spans": spans, "first_page": first_page},
    )


@app.get("/api/doc/{doc_id}.json", response_class=JSONResponse)
def api_doc(doc_id: str) -> JSONResponse:
    for p in DATA_DIR.glob("*.json"):
        b: Dict[str, Any] = json.loads(p.read_text())
        if b["doc_id"] == doc_id:
            return JSONResponse(b)
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/page-src/{page}", response_class=JSONResponse)
def page_src(page: int) -> JSONResponse:
    # Derive page→image from filenames like angv_p001.jpg
    pages: List[Dict[str, Any]] = []
    for img in sorted(IMAGES_DIR.glob("*.jpg")):
        digits: str = "".join(ch for ch in img.stem if ch.isdigit())
        num: int = int(digits) if digits else 1
        pages.append({"page": num, "src": f"/images/{img.name}"})
    for p in pages:
        if p["page"] == page:
            return JSONResponse(p)
    return JSONResponse(pages[0] if pages else {"page": 1, "src": ""})
