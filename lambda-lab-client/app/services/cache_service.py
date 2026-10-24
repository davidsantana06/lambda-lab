from chromadb.api.models.Collection import Collection
from chromadb.config import Settings
from functools import cache
from sentence_transformers import SentenceTransformer
from typing import Any, Optional
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
_TRAILING_PUNCTUATION = ".,;:!?…"


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


# Não reaproveita se a mesma pergunta já chamou tools, cujos dados são dinâmicos.
def find_repeated_answer(question: str, history: list[dict[str, Any]]) -> Optional[str]:
    normalized_question = _normalize_question(question)
    repeated_turns = [
        turn
        for turn in _split_turns(history)
        if _normalize_question(turn[0]["content"]) == normalized_question
    ]
    used_tools = any(
        message["role"] == "tool" for turn in repeated_turns for message in turn
    )
    should_reuse_answer = bool(repeated_turns) and not used_tools
    if not should_reuse_answer:
        return None

    # Uma resposta vazia do modelo fica no histórico sem conteúdo.
    return repeated_turns[-1][-1].get("content") or None


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


# Cada turno vai de uma mensagem do usuário até a próxima.
def _split_turns(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    turns = []
    for message in history:
        if message["role"] == "user":
            turns.append([])

        turns[-1].append(message)

    return turns


# Ignora caixa, espaços extras e pontuação final.
def _normalize_question(question: str) -> str:
    return " ".join(question.lower().split()).rstrip(f"{_TRAILING_PUNCTUATION} ")
