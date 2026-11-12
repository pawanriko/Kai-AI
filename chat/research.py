"""Web research for the agent loop (Phase 5): web_search + fetch_page.

Free tiers, no key where possible — the Open-Meteo pattern from the
weather tool:

- web_search uses DuckDuckGo's keyless HTML endpoint by default.
  When TAVILY_API_KEY is set in the environment, Tavily's API is
  tried first and DuckDuckGo is the fallback if Tavily fails, so a
  dead key degrades the search instead of breaking it.
- fetch_page fetches a URL the model chose and returns its text.
  It refuses non-public destinations (localhost, private ranges,
  cloud metadata addresses): the model supplies URLs, and an
  unchecked fetch would turn the agent into an SSRF probe.

Both functions return STRINGS and never raise — a failed search or
fetch is error text the model can react to, like every other tool.
Only the standard library is used (urllib + html.parser).
"""

import html
import html.parser
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

_USER_AGENT = "KAI/2.0 (personal assistant)"
_SEARCH_TIMEOUT = 15
_FETCH_TIMEOUT = 15
_MAX_FETCH_BYTES = 256 * 1024
_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")


# ---------------------------------------------------------------- web search

def _format_results(results):
    """Uniform shape for both search backends: numbered title + URL
    + snippet lines. The URL on its own line is what the report
    builder later mines for citations."""
    lines = []
    for i, result in enumerate(results, 1):
        lines.append(f"{i}. {result['title']}")
        lines.append(f"   {result['url']}")
        snippet = (result.get("snippet") or "").strip()
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def _search_tavily(query, count):
    """Tavily search API. Raises on any failure — the caller falls
    back to DuckDuckGo, so a Tavily outage is a degradation, never
    an outage of the tool itself."""
    payload = json.dumps(
        {
            "query": query,
            "max_results": count,
            "include_answer": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {os.environ.get('TAVILY_API_KEY', '')}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_SEARCH_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    results = []
    for item in body.get("results") or []:
        url = item.get("url") or ""
        if not url:
            continue
        results.append(
            {
                "title": item.get("title") or url,
                "url": url,
                "snippet": item.get("content") or "",
            }
        )
    return results


class _DuckDuckGoParser(html.parser.HTMLParser):
    """DuckDuckGo's HTML results: each hit is an <a class="result__a">
    whose href is a redirect carrying the real URL in the `uddg`
    parameter, followed by an <a class="result__snippet"> with the
    snippet text. Snippets pair with links by document order."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._capture = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if "result__a" in classes:
            href = attrs.get("href") or ""
            parsed = urllib.parse.urlparse(href)
            real = urllib.parse.parse_qs(parsed.query).get("uddg", [None])[0]
            url = urllib.parse.unquote(real) if real else href
            self.results.append({"title": "", "url": url, "snippet": ""})
            self._capture = "title"
            self._text = []
        elif "result__snippet" in classes and self.results:
            self._capture = "snippet"
            self._text = []

    def handle_data(self, data):
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._capture and self.results:
            text = html.unescape("".join(self._text)).strip()
            key = "title" if self._capture == "title" else "snippet"
            self.results[-1][key] = text
            self._capture = None


def _search_duckduckgo(query, count):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(
        {"q": query}
    )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_SEARCH_TIMEOUT) as response:
        page = response.read().decode("utf-8", errors="replace")
    parser = _DuckDuckGoParser()
    parser.feed(page)
    results = [r for r in parser.results if r["url"]]
    return results[:count]


def web_search(query, count=5):
    """Search the web. Returns numbered results with URLs, or an
    error string. `count` is clamped to 1–10."""
    query = (query or "").strip()
    if not query:
        return "Web search error: a query is required."
    count = max(1, min(10, int(count or 5)))
    if os.environ.get("TAVILY_API_KEY"):
        try:
            results = _search_tavily(query, count)
        except Exception:
            results = None
        if results:
            return _format_results(results)
        # Tavily failed or came back empty: fall through to the
        # keyless backend rather than failing the search.
    try:
        results = _search_duckduckgo(query, count)
    except Exception as exc:
        return f"Web search error: {exc}"
    if not results:
        return f"No web results found for '{query}'."
    return _format_results(results)


# ---------------------------------------------------------------- fetch page

def _check_url_public(url):
    """SSRF guard: the URL must be http(s), and every address its
    hostname resolves to must be globally routable. Raises
    ValueError with a plain reason otherwise. (DNS-rebinding
    TOCTOU is out of scope for a single-owner personal server.)"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs can be fetched")
    host = parsed.hostname
    if not host:
        raise ValueError("the URL has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"could not resolve host '{host}'")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not ip.is_global:
            raise ValueError(
                f"refusing non-public address for host '{host}'"
            )


class _TextExtractor(html.parser.HTMLParser):
    """HTML → readable text: script/style content dropped, block
    elements break lines, entities unescaped, whitespace collapsed.
    """

    _BLOCK_TAGS = {
        "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "blockquote", "section", "article", "br", "hr",
    }
    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.title = ""
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self.parts.append(data)

    def text(self):
        raw = html.unescape("".join(self.parts))
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def fetch_page(url, max_chars=4000):
    """Fetch a page and return its title + readable text, with the
    URL preserved at the top so citations survive. Refuses
    non-public URLs, non-text content, and oversized bodies."""
    url = (url or "").strip()
    if not url:
        return "Fetch error: a URL is required."
    try:
        _check_url_public(url)
    except ValueError as exc:
        return f"Fetch error: {exc}"
    max_chars = max(500, min(20000, int(max_chars or 4000)))
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": _USER_AGENT}
        )
        with urllib.request.urlopen(
            request, timeout=_FETCH_TIMEOUT
        ) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return (
                    f"Fetch error: {url} is {content_type or 'unknown'}"
                    " content, not a readable page."
                )
            raw = response.read(_MAX_FETCH_BYTES + 1)
    except Exception as exc:
        return f"Fetch error: {exc}"
    if len(raw) > _MAX_FETCH_BYTES:
        return f"Fetch error: {url} is too large to read."
    text = raw.decode("utf-8", errors="replace")
    if "text/html" in content_type:
        extractor = _TextExtractor()
        extractor.feed(text)
        title = html.unescape(extractor.title).strip() or url
        body = extractor.text()
    else:
        title = url
        body = text
    if not body.strip():
        return f"Fetch error: {url} had no readable text."
    return f"Title: {title}\nURL: {url}\n\n{body[:max_chars]}"


def extract_urls(text):
    """Every http(s) URL in a piece of text, in order. Used by the
    report builder to mine citations out of stored traces."""
    return _URL_RE.findall(text or "")
