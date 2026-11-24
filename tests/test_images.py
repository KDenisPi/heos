import httpx
import pytest

from heos_home.services.images import API_PREFIX, ImageCache, ImageError, image_key
from tests.conftest import PID

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100


def make_transport(calls, responses=None):
    responses = responses or {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return responses.get(str(request.url)) or httpx.Response(
            200, content=PNG, headers={"content-type": "image/png"})

    return httpx.MockTransport(handler)


@pytest.fixture
async def cache(tmp_path):
    calls = []
    c = ImageCache(tmp_path / "img", transport=make_transport(calls))
    c.calls = calls
    await c.start()
    yield c
    await c.stop()


def test_key_is_stable_and_keeps_extension():
    url = "https://x.example/logos/amazon.png"
    assert image_key(url) == image_key(url)
    assert image_key(url).endswith(".png")
    assert not image_key("https://x.example/cover?id=5").endswith(".png")


async def test_localize_rewrites_and_keeps_remote(cache):
    item = cache.localize({"name": "Amazon", "image_url": "https://x.example/a.png"})
    assert item["image_url"].startswith(API_PREFIX)
    assert item["image_url_remote"] == "https://x.example/a.png"
    assert cache.localize({"name": "x", "image_url": ""}) == {"name": "x", "image_url": ""}


async def test_downloads_once_then_serves_from_disk(cache):
    url = "https://x.example/a.png"
    key = cache.register(url).removeprefix(API_PREFIX)
    path = await cache.get(key)
    assert path.read_bytes() == PNG
    await cache.get(key)
    assert cache.calls == [url]
    assert cache.media_type(key) == "image/png"


async def test_unregistered_key_is_refused(cache):
    with pytest.raises(KeyError):
        await cache.get("deadbeef.png")
    assert cache.calls == []


async def test_index_survives_restart(tmp_path):
    calls = []
    c1 = ImageCache(tmp_path / "img", transport=make_transport(calls))
    await c1.start()
    key = c1.register("https://x.example/a.png").removeprefix(API_PREFIX)
    await c1.get(key)
    await c1.stop()
    c2 = ImageCache(tmp_path / "img", transport=make_transport(calls))
    await c2.start()
    assert c2.known(key)
    assert (await c2.get(key)).read_bytes() == PNG
    assert len(calls) == 1
    await c2.stop()


async def test_rejects_non_images_and_errors(tmp_path):
    bad = {
        "https://x.example/page.png": httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        "https://x.example/gone.png": httpx.Response(404),
    }
    c = ImageCache(tmp_path / "img", transport=make_transport([], bad))
    await c.start()
    for url in bad:
        with pytest.raises(ImageError):
            await c.get(c.register(url).removeprefix(API_PREFIX))
    await c.stop()


async def test_evicts_least_recently_used(tmp_path):
    c = ImageCache(tmp_path / "img", max_bytes=250, transport=make_transport([]))
    await c.start()
    keys = [c.register(f"https://x.example/{i}.png").removeprefix(API_PREFIX) for i in range(3)]
    for k in keys:
        await c.get(k)
    files = {p.name for p in (tmp_path / "img").iterdir()} - {"index.json"}
    assert keys[0] not in files and keys[2] in files
    await c.stop()


async def test_sources_endpoint_serves_local_logos(app_env, tmp_path):
    app, svc, http = app_env
    await svc.images.stop()
    calls = []
    svc.images = ImageCache(tmp_path / "img2", transport=make_transport(calls))
    await svc.images.start()

    sources = (await http.get("/sources")).json()["sources"]
    amazon = next(s for s in sources if s["name"] == "Amazon Music")
    assert amazon["image_url"].startswith("/api/v1/images/")
    assert amazon["image_url_remote"].endswith("/amazon.png")

    r = await http.get(amazon["image_url"].removeprefix("/api/v1"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == PNG
    assert (await http.get("/images/0000.png")).status_code == 404
