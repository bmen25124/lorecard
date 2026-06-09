from typing import Literal
from html_to_markdown import convert_to_markdown
import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag as Bs4Tag  # type: ignore
from urllib.parse import unquote, urlparse


SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_html(html_content: str) -> str:
    """
    Cleans an HTML string by trying to extract the main content,
    removing unwanted elements and attributes.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "lxml")

    content_selectors = [
        "article",
        "#article",
        ".article",
        "main",
        "#main",
        ".main",
        '[role="main"]',
        "#content",
        ".content",
        ".post",
    ]

    content = None
    for selector in content_selectors:
        selected = soup.select(selector)
        if len(selected) == 1:
            content = selected[0]
            break

    target = content if content else soup.body
    if not target:
        target = soup

    elements_to_remove = [
        "header",
        "footer",
        "nav",
        '[role="navigation"]',
        ".sidebar",
        '[role="complementary"]',
        ".nav",
        ".menu",
        ".header",
        ".footer",
        ".advertisement",
        ".ads",
        ".cookie-notice",
        ".social-share",
        ".related-posts",
        ".comments",
        "#comments",
        ".popup",
        ".modal",
        ".overlay",
        ".banner",
        ".alert",
        ".notification",
        ".subscription",
        ".newsletter",
        ".share-buttons",
        "script",
        "style",
        "noscript",
        "iframe",
        "button",
        "form",
        "input",
        "textarea",
        "select",
        ".noprint",
    ]

    for element in target.select(", ".join(elements_to_remove)):
        element.decompose()

    for html_element in target.find_all(True):
        if isinstance(html_element, Bs4Tag):
            html_element.attrs = {
                key: value
                for key, value in html_element.attrs.items()
                if not key.startswith("on")
                and not key.startswith("aria-")
                and not key.startswith("data-")
                and not key.startswith("role")
                and key not in ["style", "target", "src"]
            }
            # if "src" in html_element.attrs:
            #     src = html_element.attrs["src"]
            #     if isinstance(src, str) and src.startswith("data:"):
            #         html_element.attrs["src"] = "..."

    cleaned_html = target.decode_contents()

    # I'm not sure about this
    # cleaned_html = re.sub(r"[\t\r\n]+", " ", cleaned_html)
    # cleaned_html = re.sub(r"\s{2,}", " ", cleaned_html)
    cleaned_html = cleaned_html.strip()

    return cleaned_html


def html_to_markdown(html_content: str) -> str:
    cleaned_html_str = clean_html(html_content)
    return convert_to_markdown(cleaned_html_str).strip()


def get_fandom_api_url_and_page_title(url: str) -> tuple[str, str] | None:
    parsed_url = urlparse(url)
    hostname = parsed_url.hostname or ""
    if not hostname.endswith(".fandom.com") or not parsed_url.path.startswith("/wiki/"):
        return None

    page_title = parsed_url.path.removeprefix("/wiki/")
    if not page_title:
        return None

    return f"{parsed_url.scheme}://{parsed_url.netloc}/api.php", unquote(page_title)


async def get_fandom_api_html(
    client: httpx.AsyncClient, url: str, timeout: int
) -> str | None:
    fandom_api_request = get_fandom_api_url_and_page_title(url)
    if not fandom_api_request:
        return None

    api_url, fandom_page_title = fandom_api_request
    api_response = await client.get(
        api_url,
        timeout=timeout,
        headers=SCRAPER_HEADERS,
        params={
            "action": "parse",
            "page": fandom_page_title,
            "prop": "text",
            "format": "json",
        },
    )
    api_response.raise_for_status()
    html = api_response.json().get("parse", {}).get("text", {}).get("*")
    if not isinstance(html, str) or not html:
        return None

    return html


class Scraper:
    """A simple scraper to fetch and parse web content."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    async def get_content(
        self,
        url: str,
        type: Literal["html", "markdown"] = "html",
        clean: bool = False,
        pretty: bool = False,
    ) -> str:
        """
        Fetches the content of a URL.
        Returns the HTML content as a string.
        """
        cookies = {"ageVerified": "true"}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                html = await get_fandom_api_html(client, url, self.timeout)
            except (httpx.HTTPError, ValueError):
                html = None

            if html:
                if clean:
                    html = clean_html(html)
                if type == "markdown":
                    return html_to_markdown(html)
                if pretty and type == "html":
                    html = BeautifulSoup(html, "lxml").prettify()
                return html.strip()

            response = await client.get(
                url, timeout=self.timeout, cookies=cookies, headers=SCRAPER_HEADERS
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 403:
                    raise

                html = await get_fandom_api_html(client, url, self.timeout)
                if html:
                    if clean:
                        html = clean_html(html)
                    if type == "markdown":
                        return html_to_markdown(html)
                    if pretty and type == "html":
                        html = BeautifulSoup(html, "lxml").prettify()
                    return html.strip()
                raise error

            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                raise ValueError(f"Invalid content type: {content_type}")
            html = response.text
            if clean:
                html = clean_html(html)
            if type == "markdown":
                return html_to_markdown(html)

            if pretty and type == "html":
                html = BeautifulSoup(html, "lxml").prettify()
            return html.strip()
