"""Domain exceptions shared across layers. [AD-1]"""


class ValidationError(Exception):
    """Raised when input validation fails, with the offending field name."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")
