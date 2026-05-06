FROM python:3.12-slim

WORKDIR /app

# Install build deps for psycopg binary + sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model into the image so runtime startup is fast.
# The model is ~80MB and cached in /root/.cache/torch/sentence_transformers
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source
COPY . .

# Create credentials directory (populated via env vars in production)
# RUN mkdir -p credentials

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]