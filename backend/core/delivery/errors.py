class SettlementMismatch(Exception):
    def __init__(self, expected, delivered):
        self.expected = expected
        self.delivered = delivered
        super().__init__(f"settlement mismatch: expected {expected}, delivered {delivered}")


class DeliveryDeferred(Exception):
    def __init__(self, delivery_id, reason):
        self.delivery_id = delivery_id
        self.reason = reason
        super().__init__(f"delivery {delivery_id} deferred: {reason}")
