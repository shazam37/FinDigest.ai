FROM python:3.12-slim

WORKDIR /app

# Build deps: psycopg binary, sentence-transformers, reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download embedding model so runtime startup is fast (~80MB, cached in image)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .
# RUN mkdir -p credentials /tmp/research

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]