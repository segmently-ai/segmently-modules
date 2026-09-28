"""The scoring model."""


class Score:
    def __init__(self, customer_id: str):
        self.value = len(customer_id)
