class ServiceDisabled(Exception):
    """Raised when a service is disabled via kill switch."""

    def __init__(self, service: str = "service"):
        self.service = service
        super().__init__(f"service disabled: {service}")