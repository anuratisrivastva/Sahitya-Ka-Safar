"""
Pull star ratings + written reviews from Goodreads for books already on
the map, via the public RSS feed (no API key needed — Goodreads' actual
API has been closed to new keys since 2020):

  https://www.goodreads.com/review/list_rss/<user_id>?shelf=<shelf>&page=N

Matches Goodreads items against data/books_map.csv by normalized title,
and stores rating/review into data/api_cache.json (same cache the cover/
description enrichment already uses), keyed "title|author" — so
scripts/prep_data.py picks them up on its next run with no further
changes needed there.

Usage: python3 scripts/sync_goodreads.py
"""
import csv
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "books_map.csv"
CACHE_PATH = ROOT / "data" / "api_cache.json"

GOODREADS_USER = "9952703-anurati"
SHELF = "read"
USER_AGENT = "SahityaKaSafarBookMap/1.0 (personal reading-map project)"


def fetch_page(page: int):
    url = (
        f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER}"
        f"?shelf={SHELF}&page={page}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None


def clean_review(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_title(title: str) -> str:
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title)  # drop trailing series info
    title = title.split(":")[0]  # drop ": subtitle" (editions often add one)
    title = re.sub(r"[‘’'`]", "", title)  # curly vs straight apostrophes
    return re.sub(r"\s+", " ", title).strip().lower()


def fetch_all_goodreads_items():
    items = []
    page = 1
    while True:
        raw = fetch_page(page)
        if not raw:
            break
        root = ElementTree.fromstring(raw)
        page_items = root.findall(".//item")
        if not page_items:
            break
        for el in page_items:
            title = (el.findtext("title") or "").strip()
            author = (el.findtext("author_name") or "").strip()
            rating_text = (el.findtext("user_rating") or "0").strip()
            review_raw = el.findtext("user_review") or ""
            items.append({
                "title": title,
                "author": author,
                "rating": int(rating_text) if rating_text.isdigit() else 0,
                "review": clean_review(review_raw) if review_raw.strip() else "",
            })
        print(f"  fetched page {page}: {len(page_items)} items")
        page += 1
        time.sleep(0.3)
    return items


def main():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            book = (row.get("book") or "").strip()
            author = (row.get("author") or "").strip()
            if book and author:
                rows.append({"book": book, "author": author})

    print(f"Loaded {len(rows)} books from books_map.csv")
    print("Fetching Goodreads RSS feed...")
    gr_items = fetch_all_goodreads_items()
    print(f"Fetched {len(gr_items)} items from Goodreads shelf '{SHELF}'")

    gr_by_title = {}
    for item in gr_items:
        key = normalize_title(item["title"])
        gr_by_title.setdefault(key, []).append(item)

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}

    matched = 0
    matched_with_review = 0
    for row in rows:
        key = normalize_title(row["book"])
        candidates = gr_by_title.get(key)
        if not candidates:
            continue

        # Disambiguate same-title matches by author last name.
        csv_last_name = row["author"].split(",")[0].strip().lower()
        chosen = candidates[0]
        if len(candidates) > 1:
            for c in candidates:
                if csv_last_name and csv_last_name in c["author"].lower():
                    chosen = c
                    break

        if not chosen["rating"] and not chosen["review"]:
            continue

        cache_key = f"{row['book']}|{row['author']}"
        entry = cache.get(cache_key, {})
        if chosen["rating"]:
            entry["rating"] = chosen["rating"]
        if chosen["review"]:
            entry["review"] = chosen["review"]
            matched_with_review += 1
        cache[cache_key] = entry
        matched += 1

    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

    print(f"Matched {matched}/{len(rows)} books on the map to a Goodreads rating/review")
    print(f"  of which {matched_with_review} had a written review")
    print(f"Unmatched on the map: {len(rows) - matched}")

    unmatched_gr = sum(1 for k in gr_by_title if k not in {normalize_title(r['book']) for r in rows})
    print(f"Goodreads items with no corresponding row in books_map.csv: {unmatched_gr}")


if __name__ == "__main__":
    main()
