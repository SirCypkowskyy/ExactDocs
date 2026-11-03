from exactdocs_kernel import NotFoundError, ValidationError


class JobNotFoundError(NotFoundError):
    """No job with this ID exists."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} does not exist")
        self.job_id = job_id


class UnknownJobKindError(ValidationError):
    """Nothing is registered to run jobs of this kind."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"unknown job kind {kind!r}")
        self.kind = kind


class InvalidProgressError(ValidationError):
    """Progress that is negative or past its total."""

    def __init__(self, done: int, total: int) -> None:
        super().__init__(f"progress {done} of {total} is not valid")
