"""Why a step stopped. Kept free of browser imports so guardrails load before the browser daemon is configured."""


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Blocked(Exception):
    """The goal cannot progress: a guardrail refused the next action, or the page is out of reach."""


class NeedsApproval(Exception):
    """A never-do rule may apply to the next action. A person has to allow it."""

    def __init__(self, rule, action, probability):
        super().__init__(f"'{action}' may break the rule 'never {rule}' ({probability:.0%}).")
        self.rule, self.action, self.probability = rule, action, probability


class ProviderUnavailable(RuntimeError):
    """Transient provider failures exhausted the request's retry deadline."""


class ProviderRejected(RuntimeError):
    """The provider refused a request with a non-transient HTTP error, such as a revoked key."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status
