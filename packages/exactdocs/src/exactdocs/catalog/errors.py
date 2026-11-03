from exactdocs_kernel import NotFoundError, ValidationError


class EmptyVersionError(ValidationError):
    """A version label is blank."""

    def __init__(self) -> None:
        super().__init__("version must not be empty")


class LibraryNotFoundError(NotFoundError):
    """No library with this name is in the catalog."""

    def __init__(self, name: str) -> None:
        super().__init__(f"library {name!r} is not in the catalog")
        self.name = name
