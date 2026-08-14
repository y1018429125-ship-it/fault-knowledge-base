"""Semantic router for selecting Skill based on question intent."""

import math
import os
from dataclasses import dataclass
from typing import Optional

from config import ROUTER_SIMILARITY_THRESHOLD
from core.embedding import embed_texts
from core.query_parser import mask_line_tower


SKILL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Project_Skills",
    "prompt-skills",
)


@dataclass
class RouteResult:
    skill: Optional[str]
    similarity: float
    threshold: float


def _load_examples(skill_name: str) -> list[str]:
    """Load example questions for a skill."""
    path = os.path.join(SKILL_DIR, skill_name, "examples.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_skill_examples: dict[str, list[str]] = {}
_skill_embeddings: dict[str, list[list[float]]] = {}


def _load_all_skills() -> None:
    """Load examples for all available skills."""
    global _skill_examples, _skill_embeddings
    if _skill_examples:
        return

    skills = []
    if os.path.exists(SKILL_DIR):
        skills = [d for d in os.listdir(SKILL_DIR) if os.path.isdir(os.path.join(SKILL_DIR, d))]

    for skill in skills:
        examples = _load_examples(skill)
        if examples:
            _skill_examples[skill] = examples
            # 掩码开放词汇（线路名/杆塔号）后向量化：相似度比较句式结构而非词面
            _skill_embeddings[skill] = embed_texts([mask_line_tower(e) for e in examples])


def route(question: str) -> RouteResult:
    """Route a question to the best matching skill.

    Returns the skill name if max similarity >= threshold, otherwise None.
    """
    _load_all_skills()

    if not _skill_embeddings:
        return RouteResult(skill=None, similarity=0.0, threshold=ROUTER_SIMILARITY_THRESHOLD)

    query_embedding = embed_texts([mask_line_tower(question)])[0]

    best_skill = None
    best_score = 0.0
    for skill, embeddings in _skill_embeddings.items():
        for emb in embeddings:
            score = _cosine_similarity(query_embedding, emb)
            if score > best_score:
                best_score = score
                best_skill = skill

    if best_score >= ROUTER_SIMILARITY_THRESHOLD:
        return RouteResult(skill=best_skill, similarity=best_score, threshold=ROUTER_SIMILARITY_THRESHOLD)

    return RouteResult(skill=None, similarity=best_score, threshold=ROUTER_SIMILARITY_THRESHOLD)


def reset_router_cache() -> None:
    """Clear cached skill embeddings."""
    global _skill_examples, _skill_embeddings
    _skill_examples = {}
    _skill_embeddings = {}
