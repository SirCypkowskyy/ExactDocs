import pytest

from exactdocs.identity.adapters.driven.argon2id import Argon2idPasswordHasher

HORSE = "correct horse battery staple"


@pytest.fixture(scope="module")
def hasher() -> Argon2idPasswordHasher:
    return Argon2idPasswordHasher()


async def test_the_hash_is_argon2id_with_a_memory_hard_cost(
    hasher: Argon2idPasswordHasher,
) -> None:
    encoded = await hasher.hash(HORSE)

    assert encoded.startswith("$argon2id$")
    assert "m=65536" in encoded  # 64 MiB, the RFC 9106 low-memory profile
    assert HORSE not in encoded


async def test_the_same_password_hashes_differently_every_time(
    hasher: Argon2idPasswordHasher,
) -> None:
    assert await hasher.hash(HORSE) != await hasher.hash(HORSE)


async def test_verify_accepts_the_password_and_rejects_anything_else(
    hasher: Argon2idPasswordHasher,
) -> None:
    encoded = await hasher.hash(HORSE)

    assert await hasher.verify(encoded, HORSE) is True
    assert await hasher.verify(encoded, HORSE + " ") is False
    assert await hasher.verify(encoded, "") is False


@pytest.mark.parametrize("corrupt", ["", "not-a-hash", "$argon2id$v=19$m=1,t=1,p=1$bad$bad"])
async def test_a_corrupt_stored_hash_never_matches(
    hasher: Argon2idPasswordHasher, corrupt: str
) -> None:
    assert await hasher.verify(corrupt, HORSE) is False
