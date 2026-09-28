"""The payment gateway."""


def charge(customer_id: str, amount: float) -> str:
    return f"charge:{customer_id}:{amount:.2f}"


def upsell(customer_id: str) -> list[str]:
    from recommendations.engine import suggest  # imported here: recommendations imports payments
    return suggest(customer_id)
