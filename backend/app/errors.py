class ServiceError(Exception):
    """Domain error mapped to a meaningful HTTP status by the FastAPI handler."""

    def __init__(self, status_code: int, message: str, code: str = "error"):
        super().__init__(message)
        self.status_code, self.message, self.code = status_code, message, code
