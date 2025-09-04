# BJVN — Parallel Viewer

FastAPI + Jinja2 + Tailwind/DaisyUI + OpenSeadragon viewer for the Buddhist Journal of Viet Nam (BJVN).
Phase I is viewer-only (no DB), serving JSON bundles and page scans.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app 
# open http://127.0.0.1:8000
