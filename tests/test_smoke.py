"""Smoke tests to verify pytest and beanie fixture setup."""

import pytest

from src.common.db.modules import Context


def test_pytest_works() -> None:
    """Basic smoke test to verify pytest runs."""
    assert True


@pytest.mark.asyncio
async def test_beanie_fixture(beanie_fixture) -> None:
    """Test beanie fixture can create and query Context documents."""
    # Create a Context document
    context = Context(keywords="hello world", trigger_count=1)
    await context.insert()

    # Query it back
    retrieved = await Context.find_one(Context.keywords == "hello world")

    assert retrieved is not None
    assert retrieved.keywords == "hello world"
    assert retrieved.trigger_count == 1
