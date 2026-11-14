import pytest


@pytest.fixture(autouse=True)
def _clear_event_caches():
    from app import event

    event._series_cache.clear()
    event._profile_points.cache_clear()
    yield
    event._series_cache.clear()
    event._profile_points.cache_clear()
