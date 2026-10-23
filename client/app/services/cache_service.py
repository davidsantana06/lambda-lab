from sqlmodel import select
from typing import Optional
import math
import os

from database import get_session
from models import CachedAnswer
from services.llm_service import EMBEDDING_MODEL


_CACHE_SIMILARITY_THRESHOLD = float(
    os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.90")
)


def find_cached_answer(
    embedding: list[float],
) -> Optional[tuple[CachedAnswer, float]]:
    with get_session() as session:
        statement = select(CachedAnswer).where(
            CachedAnswer.embedding_model == EMBEDDING_MODEL
        )
        cached_answers = session.exec(statement).all()

    scored_answers = [
        (cached_answer, _compute_cosine_similarity(embedding, cached_answer.embedding))
        for cached_answer in cached_answers
    ]
    best_match = max(scored_answers, key=lambda pair: pair[1], default=None)
    if best_match is None or best_match[1] < _CACHE_SIMILARITY_THRESHOLD:
        return None

    return best_match


def save_cached_answer(question: str, embedding: list[float], answer: str) -> None:
    cached_answer = CachedAnswer(
        question=question,
        answer=answer,
        embedding=embedding,
        embedding_model=EMBEDDING_MODEL,
    )
    with get_session() as session:
        session.add(cached_answer)
        session.commit()


def _compute_cosine_similarity(first: list[float], second: list[float]) -> float:
    norms = math.sqrt(math.sumprod(first, first) * math.sumprod(second, second))
    if not norms:
        return 0.0

    return math.sumprod(first, second) / norms
