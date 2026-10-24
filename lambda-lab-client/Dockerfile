FROM python:3.12-slim

COPY requirements.txt /requirements.txt

RUN pip install --no-cache-dir -r /requirements.txt

# Baixa no build o modelo de embeddings que o cache_service.py carrega do disco.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

WORKDIR /app
