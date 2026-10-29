# errors
class AdapterError(Exception):
    pass


class UnsupportedRegion(AdapterError):
    pass


class InsufficientInventory(AdapterError):
    pass


class PaymentError(Exception):
    pass


class WebhookSignatureError(PaymentError):
    pass
