"""
robots.txt compliance for the website crawler (RFC 9309 behaviour).

* 2xx: parse and obey.   * 4xx: no restrictions.   * 5xx / unreachable: treat the site as disallowed for this run.
Rules are cached per origin for 24 hours.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Dict, Optional, Tuple
from urllib.robotparser import RobotFileParser

from packages.discovery.http import BOT_USER_AGENT, paced_request

logger = logging.getLogger("discovery.robots")

_TTL = 24 * 3600.0
_CACHE: Dict[str, Tuple[float, Optional[RobotFileParser], bool]] = {}


class RobotsRules:
    """Result of a robots lookup. `allow_all` / `deny_all` short-circuit the parser."""

    def __init__(self, parser: Optional[RobotFileParser], deny_all: bool = False) -> None:
        self.parser = parser
        self.deny_all = deny_all

    def can_fetch(self, url: str, user_agent: str = BOT_USER_AGENT) -> bool:
        if self.deny_all:
            return False
        if self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)


async def get_robots(url: str, timeout: float = 4.0) -> RobotsRules:
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.monotonic()
    cached = _CACHE.get(origin)
    if cached and now - cached[0] < _TTL:
        return RobotsRules(cached[1], cached[2])

    parser: Optional[RobotFileParser] = None
    deny = False
    try:
        resp = await paced_request("discovery_website_crawl", "GET", f"{origin}/robots.txt", timeout=timeout)
        if resp.status_code == 200:
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
        elif 400 <= resp.status_code < 500:
            parser = None
        else:
            deny = True
    except Exception as exc:
        logger.debug("robots.txt unreachable for %s: %s", origin, exc)
        deny = True
    _CACHE[origin] = (now, parser, deny)
    return RobotsRules(parser, deny)


def clear_cache() -> None:
    _CACHE.clear()
