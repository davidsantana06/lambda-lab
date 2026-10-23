from chromadb.api.models.Collection import Collection
from chromadb.config import Settings
from functools import cache
from sentence_transformers import SentenceTransformer
from typing import Optional
import asyncio
import chromadb
import os
import uuid


# O Dockerfile baixa este modelo no build.
_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_CACHE_PATH = "/data/cache"
_CACHE_COLLECTION = "answers"
_CACHE_SIMILARITY_THRESHOLD = float(
    os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.90")
)


# Carrega o modelo na subida do chat, e não no juiz, que dispensa o cache.
def prepare_cache() -> None:
    _load_embedding_model()
    _get_collection()


async def create_embedding(text: str) -> list[float]:
    embedding = await asyncio.to_thread(_load_embedding_model().encode, text)
    return embedding.tolist()


# O Chroma devolve a distância de cosseno, que é 1 menos a similaridade.
def find_cached_answer(embedding: list[float]) -> Optional[tuple[str, float]]:
    result = _get_collection().query(
        query_embeddings=[embedding],
        n_results=1,
        include=["metadatas", "distances"],
    )
    if not result["ids"][0]:
        return None

    similarity = 1 - result["distances"][0][0]
    if similarity < _CACHE_SIMILARITY_THRESHOLD:
        return None

    return result["metadatas"][0][0]["answer"], similarity


def save_cached_answer(question: str, embedding: list[float], answer: str) -> None:
    _get_collection().add(
        ids=[str(uuid.uuid4())],
        embeddings=[embedding],
        documents=[question],
        metadatas=[{"answer": answer}],
    )


@cache
def _load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(_EMBEDDING_MODEL, device="cpu", local_files_only=True)


@cache
def _get_collection() -> Collection:
    client = chromadb.PersistentClient(
        path=_CACHE_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        _CACHE_COLLECTION,
        configuration={"hnsw": {"space": "cosine"}},
        embedding_function=None,
    )
