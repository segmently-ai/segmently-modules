"""Suggestions from the reading history."""
from payments.gateway import charge

from .model import Score


def suggest(customer_id: str) -> list[str]:
    score = Score(customer_id)
    return [f"isbn-{score.value}"]


def buy_suggestion(customer_id: str) -> str:
    return charge(customer_id, 9.99)
