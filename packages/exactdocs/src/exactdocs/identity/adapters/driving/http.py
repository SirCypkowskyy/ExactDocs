"""REST adapter for identity: the first-run setup."""

from fastapi import APIRouter

from exactdocs.identity.dtos import AccountSummary, CreateFirstAdminCommand
from exactdocs.identity.ports.driving import CreateFirstAdmin


def build_router(*, create_first_admin: CreateFirstAdmin) -> APIRouter:
    """Expose ``POST /setup``: creates the admin, only while no account exists."""
    router = APIRouter(tags=["identity"])

    @router.post("/setup", status_code=201)
    async def setup(command: CreateFirstAdminCommand) -> AccountSummary:
        return await create_first_admin(command)

    return router
