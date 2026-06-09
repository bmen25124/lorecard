import httpx
import pytest

from services.scraper import get_fandom_api_url_and_page_title, get_fandom_category_html


def test_get_fandom_api_url_and_page_title_extracts_fandom_wiki_path():
    assert (
        get_fandom_api_url_and_page_title(
            "https://elderscrolls.fandom.com/wiki/Lydia_(Skyrim)?so=search"
        )
        == ("https://elderscrolls.fandom.com/api.php", "Lydia_(Skyrim)")
    )


def test_get_fandom_api_url_and_page_title_ignores_non_fandom_urls():
    assert (
        get_fandom_api_url_and_page_title("https://example.com/wiki/Lydia_(Skyrim)")
        is None
    )


def test_get_fandom_api_url_and_page_title_extracts_fandom_category_pages():
    assert (
        get_fandom_api_url_and_page_title(
            "https://elderscrolls.fandom.com/wiki/Category:Skyrim:_Locations"
        )
        == ("https://elderscrolls.fandom.com/api.php", "Category:Skyrim:_Locations")
    )


@pytest.mark.asyncio
async def test_get_fandom_category_html_includes_pagination_link():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["cmcontinue"] == "next-token"
        return httpx.Response(
            200,
            json={
                "query": {
                    "categorymembers": [
                        {"title": "Abandoned House (Markarth)"},
                    ]
                },
                "continue": {
                    "cmcontinue": "after-token",
                    "continue": "-||",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        html = await get_fandom_category_html(
            client,
            "https://elderscrolls.fandom.com/api.php",
            "Category:Skyrim:_Locations",
            "https://elderscrolls.fandom.com/wiki/Category:Skyrim:_Locations?cmcontinue=next-token",
            10,
        )

    assert html is not None
    assert 'class="category-page__member-link"' in html
    assert "/wiki/Abandoned_House_(Markarth)" in html
    assert 'class="category-page__pagination-next"' in html
    assert "cmcontinue=after-token" in html
