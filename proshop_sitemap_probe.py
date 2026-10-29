#!/usr/bin/env python3
"""Read-only Proshop public sitemap discovery probe, no state or Discord."""
import gzip
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

BASE = "https://www.proshop.dk/"
PATHS = ("sitemap.xml", "robots.txt")


def attempt(url):
    try:
        result = requests.get(
            url,
            headers={"User-Agent": "Pokemon-Restock-Research/1.0"},
            timeout=25,
            stream=True,
        )
        buffer = bytearray()
        for chunk in result.iter_content(chunk_size=65536):
            buffer.extend(chunk)
            if len(buffer) > 8_000_000:
                break
        data = bytes(buffer)
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        info = {
            "url": url, "code": result.status_code,
            "content_type": result.headers.get("content-type"),
            "chars": len(data), "truncated": len(buffer)>8_000_000,
        }
        if "<html" in data[:1500].lower().decode("utf-8","replace"):
            info["warning"] = "HTML served instead of XML"
            return info
        try:
            root = ET.fromstring(data)
            namespace = re.sub(r"\}.*", "}", root.tag) if "}" in root.tag else ""
            locs = [elem.text for elem in root.iter(namespace+"loc") if elem.text]
            info["xml_root"] = root.tag
            info["entries"] = len(locs)
            info["samples"] = locs[:7]
            info["pokemon_url_count"] = sum("pokemon" in (u or "").lower() for u in locs)
            info["pokemon_samples"] = [u for u in locs if "pokemon" in u.lower()][:7]
            return info
        except (ET.ParseError, UnicodeDecodeError):
            info["prefix"] = data[:140].decode("utf-8","replace")
            return info
    except (requests.RequestException, OSError, ValueError) as ex:
        return {"url": url, "error": type(ex).__name__, "message": str(ex)[:150]}


if __name__ == "__main__":
    for suffix in PATHS:
        print("PROSHOP SITEMAP",attempt(BASE+suffix), flush=True)
