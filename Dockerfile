# Simple, production-friendly image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
COPY templates ./templates
COPY data ./data
COPY images ./images

EXPOSE 8080

# Uvicorn on Fly uses PORT env; default to 8080
ENV PORT=8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
