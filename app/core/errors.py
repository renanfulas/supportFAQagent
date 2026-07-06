class SupportFAQError(Exception):
    error_code = "supportfaq_error"


class ProviderError(SupportFAQError):
    error_code = "provider_error"

    def __init__(
        self,
        message: str = "provider error",
        *,
        failure_kind: str = "provider_error",
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


class RetrievalError(SupportFAQError):
    error_code = "retrieval_error"


class DatabaseUnavailableError(SupportFAQError):
    error_code = "database_unavailable"


class TransactionBusinessError(SupportFAQError):
    """Base for domain-level rejections raised inside ``DatabaseRuntime.transaction()``.

    Unlike a real pool/connection failure, these represent a valid business
    decision (invalid state transition, record not found, ...) computed from
    data already read inside the transaction. ``DatabaseRuntime.transaction()``
    lets subclasses of this propagate unchanged instead of masking them as
    ``DatabaseUnavailableError``.
    """

    error_code = "transaction_business_error"
