"""Browser — open a URL in the default browser.

ponytail: the old web_search/play_youtube handlers (which scraped youtube.com over
HTTP) died with the LLM that called them. TONY makes no outbound requests of its own;
`webbrowser.open` just hands a URL to the browser. Keep it that way — the README's
privacy claim should stay checkable by grepping this file.
"""
from __future__ import annotations
import webbrowser


def open_url(url: str) -> str:
    if not url:
        return "No URL given."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."
