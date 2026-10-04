"""Shared domain errors for the provider-independent Founder Graph modules."""


class DomainValidationError(ValueError):
    """Raised when a Founder Graph value violates its domain contract."""
