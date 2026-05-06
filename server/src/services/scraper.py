from typing import Literal
from html_to_markdown import convert_to_markdown
import httpx
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup
from bs4.element import Tag as Bs4Tag  # type: ignore


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


def get_fandom_api_request(url: str) -> tuple[str, dict[str, str]] | None:
    parsed_url = urlparse(url)
    if not parsed_url.netloc.endswith(".fandom.com"):
        return None

    wiki_prefix = "/wiki/"
    if not parsed_url.path.startswith(wiki_prefix):
        return None

    page_name = unquote(parsed_url.path[len(wiki_prefix) :])
    if not page_name:
        return None

    api_url = f"{parsed_url.scheme}://{parsed_url.netloc}/api.php"
    return (
        api_url,
        {
            "action": "parse",
            "page": page_name,
            "prop": "text",
            "redirects": "1",
            "format": "json",
        },
    )


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
            response = await client.get(url, timeout=self.timeout, cookies=cookies)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 403:
                    raise

                fandom_request = get_fandom_api_request(url)
                if not fandom_request:
                    raise

                api_url, params = fandom_request
                response = await client.get(api_url, timeout=self.timeout, params=params)
                response.raise_for_status()
                data = response.json()
                html = data.get("parse", {}).get("text", {}).get("*")
                if not isinstance(html, str):
                    raise ValueError("Invalid Fandom API response: missing parsed HTML")

                if clean:
                    html = clean_html(html)
                if type == "markdown":
                    return html_to_markdown(html)

                if pretty and type == "html":
                    html = BeautifulSoup(html, "lxml").prettify()
                return html.strip()

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
