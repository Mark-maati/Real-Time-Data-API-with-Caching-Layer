import pytest
from app.services.fetcher import _is_open, _record_failure, _record_success, _circuit, FAILURE_THRESHOLD


@pytest.fixture(autouse=True)
def clear_circuit():
    _circuit.clear()
    yield
    _circuit.clear()


@pytest.mark.asyncio
async def test_circuit_starts_closed():
    assert not await _is_open("http://example.com/api")


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold():
    url = "http://example.com/api"
    for _ in range(FAILURE_THRESHOLD):
        await _record_failure(url)
    assert await _is_open(url)


@pytest.mark.asyncio
async def test_circuit_resets_on_success():
    url = "http://example.com/api"
    await _record_failure(url)
    await _record_failure(url)
    await _record_success(url)
    assert not await _is_open(url)
