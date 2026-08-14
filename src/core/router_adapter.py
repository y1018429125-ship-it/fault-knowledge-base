"""Adapter to bridge semantic_router and engine without circular imports."""

from router.semantic_router import route


def route_query(question: str):
    """Wrap router.route to provide a stable interface for engine."""
    return route(question)
