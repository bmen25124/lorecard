from services.scraper import get_fandom_page_title


def test_get_fandom_page_title_extracts_fandom_wiki_path():
    assert (
        get_fandom_page_title(
            "https://elderscrolls.fandom.com/wiki/Lydia_(Skyrim)?so=search"
        )
        == "Lydia_(Skyrim)"
    )


def test_get_fandom_page_title_ignores_non_fandom_urls():
    assert get_fandom_page_title("https://example.com/wiki/Lydia_(Skyrim)") is None
