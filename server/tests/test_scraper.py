import httpx
import pytest

from services.scraper import Scraper
from services import scraper


@pytest.mark.asyncio
async def test_fandom_403_falls_back_to_mediawiki_api(monkeypatch):
    fandom_url = "https://fallout.fandom.com/wiki/The_Ghoul"
    calls = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            request = httpx.Request("GET", url)

            if url == fandom_url:
                return httpx.Response(403, request=request)

            assert url == "https://fallout.fandom.com/api.php"
            assert kwargs["params"]["action"] == "parse"
            assert kwargs["params"]["page"] == "The_Ghoul"
            assert kwargs["params"]["prop"] == "text"
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "text": {
                            "*": "<main><p>Cooper Howard became known as The Ghoul.</p></main>"
                        }
                    }
                },
                headers={"Content-Type": "application/json"},
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    content = await Scraper().get_content(fandom_url, type="markdown", clean=True)

    assert "Cooper Howard became known as The Ghoul." in content
    assert [url for url, _ in calls] == [
        fandom_url,
        "https://fallout.fandom.com/api.php",
    ]


@pytest.mark.asyncio
async def test_non_fandom_403_does_not_use_mediawiki_fallback(monkeypatch):
    blocked_url = "https://example.com/blocked"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(httpx.HTTPStatusError):
        await Scraper().get_content(blocked_url, type="markdown", clean=True)


def test_html_to_markdown_accepts_new_conversion_result(monkeypatch):
    class ConversionResult:
        content = "Converted markdown"

    monkeypatch.setattr(
        scraper, "convert_html_to_markdown", lambda html: ConversionResult()
    )

    assert scraper.html_to_markdown("<p>Converted markdown</p>") == "Converted markdown"
