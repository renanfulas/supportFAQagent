class SupportFAQError(Exception):
    error_code = "supportfaq_error"


class ProviderError(SupportFAQError):
    error_code = "provider_error"


class RetrievalError(SupportFAQError):
    error_code = "retrieval_error"
