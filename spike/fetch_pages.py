"""Fetch the spike's sample pages (task P0-4).

A rehearsal of the Phase 2 fetcher: polite headers, timeouts, trafilatura extraction, and
a content hash over the EXTRACTED TEXT rather than raw HTML (decision D-07).

Input: spike/urls.txt, one entry per line, optional tab-separated label.

    https://example.com            normal
    https://somefirm.com/about     dud
    https://somerecruiter.com      recruiter

Labels drive the automated rubric checks in verify.py. `dud` means "real company, no
signal worth acting on"; `recruiter` means "must be rejected as an excluded target".
"""

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import trafilatura

SPIKE = Path(__file__).parent
PAGES = SPIKE / "pages"
USER_AGENT = "ProspectingEngine/0.1 (personal research; +local)"


def slugify(url: str) -> str:
    slug = re.sub(r"^https?://(www\.)?", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
    return slug[:80]


def fetch(url: str, label: str) -> dict | None:
    try:
        response = httpx.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED {url}: {type(exc).__name__}: {exc}")
        return None

    extracted = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=True,
        with_metadata=True,
        output_format="json",
    )
    if not extracted:
        print(f"  NO TEXT EXTRACTED {url}")
        return None

    data = json.loads(extracted)
    text = (data.get("text") or "").strip()
    if len(text) < 200:
        print(f"  TOO SHORT ({len(text)} chars) {url}")
        return None

    slug = slugify(url)
    (PAGES / f"{slug}.txt").write_text(text)
    meta = {
        "url": url,
        "label": label,
        "slug": slug,
        "title": data.get("title"),
        "published_at": data.get("date"),
        "fetched_at": datetime.now(UTC).isoformat(),
        "http_status": response.status_code,
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "text_chars": len(text),
    }
    (PAGES / f"{slug}.json").write_text(json.dumps(meta, indent=2))
    print(f"  OK {slug} ({len(text)} chars, label={label})")
    return meta


def main() -> int:
    urls_file = SPIKE / "urls.txt"
    if not urls_file.exists():
        print(f"Create {urls_file} first. See this file's docstring for the format.")
        return 1

    PAGES.mkdir(exist_ok=True)
    entries = []
    for line in urls_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s+", line, maxsplit=1)
        entries.append((parts[0], parts[1].strip() if len(parts) > 1 else "normal"))

    print(f"Fetching {len(entries)} pages into {PAGES}")
    ok = sum(1 for url, label in entries if fetch(url, label) is not None)
    print(f"\n{ok}/{len(entries)} fetched successfully")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
