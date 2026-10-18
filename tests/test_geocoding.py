import pytest

from services.errors import ExternalDataError
from services.geocoding import get_coordinates
from tests.helpers import FakeAPI, mapbox_feature, mapbox_response, ok

pytestmark = pytest.mark.anyio


async def test_geocoding_returns_longitude_latitude() -> None:
    api = FakeAPI(mapbox_response())

    assert await get_coordinates(api.client, "Honolulu", "HI") == (-157.86, 21.31)


async def test_geocoding_searches_city_and_state_in_us() -> None:
    api = FakeAPI(ok({"features": []}))

    await get_coordinates(api.client, "Honolulu", "HI")

    assert api.requests[0].url.params["q"] == "Honolulu, HI"
    assert api.requests[0].url.params["country"] == "us"


async def test_geocoding_skips_similar_names() -> None:
    # Mapbox returned Adako, North Carolina first for "Adak"
    api = FakeAPI(
        mapbox_response(
            mapbox_feature("Adako", "NC", (-81.70436, 35.90482)),
            mapbox_feature("Adak", "AK", (-176.639163, 51.873833)),
        )
    )

    assert await get_coordinates(api.client, "Adak", "AK") == (-176.639163, 51.873833)


async def test_geocoding_skips_other_states() -> None:
    api = FakeAPI(mapbox_response(mapbox_feature("Adak", "AK")))

    assert await get_coordinates(api.client, "Adak", "NC") is None


async def test_geocoding_skips_place_without_state() -> None:
    api = FakeAPI(ok({"features": [{"properties": {"name": "Adak"}}]}))

    assert await get_coordinates(api.client, "Adak", "AK") is None


async def test_geocoding_ignores_capitals_and_extra_spaces() -> None:
    api = FakeAPI(mapbox_response(mapbox_feature("Los Angeles", "CA")))

    assert await get_coordinates(api.client, "  los   ANGELES ", "CA") is not None


async def test_geocoding_city_not_found() -> None:
    api = FakeAPI(ok({"features": []}))

    assert await get_coordinates(api.client, "NotARealCity", "HI") is None


async def test_geocoding_caches_each_city_and_state() -> None:
    api = FakeAPI(mapbox_response())

    first = await get_coordinates(api.client, "Honolulu", "HI")
    second = await get_coordinates(api.client, "  honolulu ", "HI")

    assert first == second
    assert len(api.requests) == 1


async def test_geocoding_bad_data() -> None:
    api = FakeAPI(ok({"features": [{"properties": {}}]}))

    with pytest.raises(ExternalDataError):
        await get_coordinates(api.client, "Honolulu", "HI")
