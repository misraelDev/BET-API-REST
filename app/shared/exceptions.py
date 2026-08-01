class ApiSportsError(RuntimeError):
    """Raised when an API-Sports product cannot satisfy a request."""


class ApiSportsRateLimitError(ApiSportsError):
    """Raised when API-Sports temporarily rejects requests due to rate limits."""


class ApiSportsDailyLimitError(ApiSportsError):
    """Raised when API-Sports has exhausted the account's daily quota."""


class ApiSportsUnavailableError(ApiSportsError):
    """Raised when API-Sports cannot be used due to account access state."""
