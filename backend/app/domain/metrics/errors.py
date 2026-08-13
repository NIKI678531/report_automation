class CalculationError(ValueError):
    """A deterministic calculation cannot proceed because its inputs are incomplete.

    Mirrors ``document.DocumentValidationError`` so the API layer can turn a domain failure into
    the ``error_code / field / entity_id / message / severity / fix_hint`` envelope instead of a
    bare 500. Subclasses ``ValueError`` so existing ``except ValueError`` callers keep working.
    """

    def __init__(self, error_code: str, message: str, field: str, fix_hint: str, entity_id: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field = field
        self.entity_id = entity_id
        self.fix_hint = fix_hint
