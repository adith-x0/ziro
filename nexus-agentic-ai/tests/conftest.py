import pytest
import pytest_asyncio
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    """Create FastAPI application for testing."""
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client fixture."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
