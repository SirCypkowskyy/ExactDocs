"""A stand-in for a database connection pool."""


class Database:
    """Counts rows once connected."""

    instances: list["Database"] = []

    def __init__(self) -> None:
        self.connected = False
        Database.instances.append(self)

    async def connect(self) -> None:
        """Open the pool."""
        self.connected = True

    async def disconnect(self) -> None:
        """Close the pool."""
        self.connected = False

    async def count(self) -> int:
        """How many rows there are."""
        if not self.connected:
            raise RuntimeError("the database is not connected")
        return 42
