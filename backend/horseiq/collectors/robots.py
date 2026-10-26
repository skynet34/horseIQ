"""robots.txt guard for any HTTP fetch HorseIQ performs against a third-party website.

Checked on 2026-10-26:
  tjk.org/robots.txt      -> "User-agent: *  Disallow: /" (also explicitly blocks Claude-User, GPTBot ...)
  accurace.net/robots.txt -> "User-agent: *  Disallow: /network/*"
So neither site's race pages may be crawled. Licensed APIs (key-based) are separate agreements
and do not go through this guard.
"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "HorseIQ-Collector/0.4 (+contact: project owner)"


class RobotsDisallowed(PermissionError):
    pass


@lru_cache(maxsize=32)
def _parser(origin: str) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        resp = httpx.get(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True)
        rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
    except httpx.HTTPError:
        rp.parse(["User-agent: *", "Disallow: /"])  # unknown -> be conservative
    return rp


def check_allowed(url: str, user_agent: str = USER_AGENT) -> None:
    parts = urlsplit(url)
    if not _parser(f"{parts.scheme}://{parts.netloc}").can_fetch(user_agent, url):
        raise RobotsDisallowed(f"robots.txt bu adrese otomatik erişime izin vermiyor: {url}")
