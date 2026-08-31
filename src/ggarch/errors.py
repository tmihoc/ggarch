"""ggarch error types."""


class GgarchError(Exception):
    """Base error."""


class ParseError(GgarchError):
    """Syntax or grammar error in source."""


class ValidationError(GgarchError):
    """Semantic error: references to undeclared nodes, edges, or behaviours."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        s = super().__str__()
        if self.hint:
            s += f"\n  hint: {self.hint}"
        return s
