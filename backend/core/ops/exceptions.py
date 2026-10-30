class ServiceDisabled(Exception):
    """Raised when a service is disabled via kill switch."""

    def __init__(self, service: str = "service"):
        self.service = service
        super().__init__(f"service disabled: {service}")


class UnsupportedRegion(Exception):
    """Raised when a region or account is not supported."""

    def __init__(self, message: str = "unsupported region"):
        self.message = message
        super().__init__(message)


class SupplierDown(Exception):
    """Raised when the supplier is unavailable."""

    def __init__(self, message: str = "supplier down"):
        self.message = message
        super().__init__(message)


class OutOfStock(Exception):
    """Raised when a prize is out of stock."""

    def __init__(self, message: str = "out of stock"):
        self.message = message
        super().__init__(message)