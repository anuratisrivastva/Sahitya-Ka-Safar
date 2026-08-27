"""
Data-prep script for Sahitya Ka Safar.

Reads data/books_map.csv, resolves a coordinate for each book, looks up a
cover image + short description per unique (title, author) via Open Library
and Google Books, caches raw API responses locally, and writes:

  data/books.json        - enriched records the frontend loads
  data/review_flags.md   - books whose description had to be generated
                            (not sourced from an API), for a tone check

Usage: python3 scripts/prep_data.py
"""
import csv
import difflib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from country_coords import resolve_coords

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "books_map.csv"
CACHE_PATH = ROOT / "data" / "api_cache.json"
OUTPUT_PATH = ROOT / "data" / "books.json"
REVIEW_PATH = ROOT / "data" / "review_flags.md"

USER_AGENT = "SahityaKaSafarBookMap/1.0 (personal reading-map project)"
REQUEST_DELAY = 0.15
DESC_MAX_CHARS = 220
MAX_WORKERS = 8


def http_get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def display_author(author: str) -> str:
    """CSV stores 'Last, First' — flip to natural reading order for
    display and for search queries (Open Library matches better on it)."""
    if "," in author:
        last, first = author.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return author.strip()


def clean_title_for_search(title: str) -> str:
    """Strip a trailing parenthetical (series/volume info) that hurts
    search matching, e.g. 'A Prayer for the Crown-Shy (Monk & Robot, #2)'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def trim_description(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences[:2]:
        candidate = (out + " " + s).strip() if out else s
        if len(candidate) > DESC_MAX_CHARS:
            break
        out = candidate
    if not out:
        out = text[:DESC_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return out


def openlibrary_description(work_key: str):
    data = http_get_json(f"https://openlibrary.org{work_key}.json")
    if not data:
        return None
    desc = data.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")
    if isinstance(desc, str) and desc.strip():
        return desc
    return None


def googlebooks_description(title: str, author: str):
    q = urllib.parse.quote(f'intitle:{title} inauthor:{author}')
    data = http_get_json(f"https://www.googleapis.com/books/v1/volumes?q={q}&maxResults=1")
    if not data or not data.get("items"):
        return None
    info = data["items"][0].get("volumeInfo", {})
    return info.get("description")


SPAM_PUBLISHERS = {"supersummary", "bookrags", "course hero", "worth books", "briefbooks"}
SPAM_TITLE_RE = re.compile(r"study guide|summary (of|&|and)|book club discussion|sparknotes", re.I)


def is_reasonable_match(clean_title: str, doc: dict) -> bool:
    """Open Library's search sometimes ranks unrelated 'study guide' spam
    entries above the real book — reject those instead of showing a
    confidently wrong cover."""
    doc_title = (doc.get("title") or "").strip()
    if not doc_title:
        return False
    if any(name.strip().lower() in SPAM_PUBLISHERS for name in doc.get("author_name", [])):
        return False
    if SPAM_TITLE_RE.search(doc_title):
        return False
    ratio = difflib.SequenceMatcher(None, clean_title.lower(), doc_title.lower()).ratio()
    return ratio > 0.45


def openlibrary_search(query: str, clean_title: str):
    q = urllib.parse.quote(query)
    data = http_get_json(f"https://openlibrary.org/search.json?q={q}&limit=3")
    time.sleep(REQUEST_DELAY)
    if not data:
        return None
    for doc in data.get("docs", []):
        if is_reasonable_match(clean_title, doc):
            return doc
    return None


def fetch_book_meta(title: str, author: str) -> dict:
    """Network-only lookup (no cache access) — safe to run in a worker thread."""
    result = {"cover_url": None, "description": None, "description_source": None}

    clean_title = clean_title_for_search(title)
    author_name = display_author(author)

    doc = openlibrary_search(f"{clean_title} {author_name}", clean_title)
    if not doc:
        doc = openlibrary_search(clean_title, clean_title)

    if doc:
        cover_i = doc.get("cover_i")
        if cover_i:
            result["cover_url"] = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg?default=false"
        elif doc.get("isbn"):
            result["cover_url"] = f"https://covers.openlibrary.org/b/isbn/{doc['isbn'][0]}-M.jpg?default=false"

        work_key = doc.get("key")
        if work_key:
            desc = openlibrary_description(work_key)
            time.sleep(REQUEST_DELAY)
            if desc:
                result["description"] = trim_description(desc)
                result["description_source"] = "openlibrary"

    if not result["description"]:
        desc = googlebooks_description(title, author)
        time.sleep(REQUEST_DELAY)
        if desc:
            result["description"] = trim_description(desc)
            result["description_source"] = "googlebooks"

    return result


GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))  # ~137.5°, sunflower phyllotaxis


def jitter_group(base_lat: float, base_lon: float, n: int):
    """Spread n points around (base_lat, base_lon) in a sunflower spiral —
    radius grows with each point so dense clusters (e.g. India's ~40 books)
    fan out instead of crowding on a single fixed-radius ring."""
    if n == 1:
        return [(base_lat, base_lon)]
    lon_scale = max(math.cos(math.radians(base_lat)), 0.2)
    points = []
    for i in range(n):
        r = 1.1 * math.sqrt(i + 1)
        theta = i * GOLDEN_ANGLE
        dlat = r * math.sin(theta)
        dlon = (r * math.cos(theta)) / lon_scale
        points.append((round(base_lat + dlat, 4), round(base_lon + dlon, 4)))
    return points


def main():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            book = (row.get("book") or "").strip()
            author = (row.get("author") or "").strip()
            if not book or not author:
                continue
            rows.append({
                "book": book,
                "author": author,
                "country": (row.get("country") or "").strip(),
                "region": (row.get("region") or "").strip(),
            })

    print(f"Loaded {len(rows)} books from {CSV_PATH.name}")

    # Resolve base coordinates and group rows sharing the same point.
    unresolved = []
    groups = defaultdict(list)
    for idx, row in enumerate(rows):
        coords = resolve_coords(row["country"], row["region"])
        if coords is None:
            unresolved.append(row)
            coords = (0.0, 0.0)
        groups[coords].append(idx)

    if unresolved:
        print(f"WARNING: {len(unresolved)} rows had no coordinate match:")
        for r in unresolved:
            print(f"  - {r['book']!r} ({r['country']!r}/{r['region']!r})")

    final_coords = [None] * len(rows)
    for (base_lat, base_lon), idxs in groups.items():
        for offset, i in zip(jitter_group(base_lat, base_lon, len(idxs)), idxs):
            final_coords[i] = offset

    cache = load_cache()

    unique_keys = sorted({(r["book"], r["author"]) for r in rows})
    to_fetch = [(t, a) for (t, a) in unique_keys if f"{t}|{a}" not in cache]
    print(f"{len(unique_keys)} unique (title, author) pairs, {len(to_fetch)} need fetching "
          f"({len(unique_keys) - len(to_fetch)} already cached)")

    if to_fetch:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_book_meta, t, a): (t, a) for t, a in to_fetch}
            done = 0
            for future in as_completed(futures):
                t, a = futures[future]
                cache[f"{t}|{a}"] = future.result()
                done += 1
                if done % 20 == 0 or done == len(to_fetch):
                    print(f"  fetched {done}/{len(to_fetch)}...")
                    save_cache(cache)
        save_cache(cache)

    enriched = []
    generated_flags = []
    no_cover_flags = []

    for i, row in enumerate(rows):
        lat, lon = final_coords[i]
        meta = cache[f"{row['book']}|{row['author']}"]

        author_name = display_author(row["author"])

        if not meta["description"]:
            meta = dict(meta)
            place = row["region"] or row["country"]
            meta["description"] = f"{row['book']} by {author_name}, from {place}."
            meta["description_source"] = "generated"

        record = {
            "id": i,
            "book": row["book"],
            "author": row["author"],
            "author_display": author_name,
            "country": row["country"],
            "region": row["region"],
            "lat": lat,
            "lon": lon,
            "cover_url": meta["cover_url"],
            "description": meta["description"],
            "description_source": meta["description_source"],
        }
        enriched.append(record)

        if meta["description_source"] == "generated":
            generated_flags.append(record)
        if not meta["cover_url"]:
            no_cover_flags.append(record)

        if (i + 1) % 25 == 0:
            print(f"  processed {i + 1}/{len(rows)}...")

    OUTPUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))
    print(f"Wrote {len(enriched)} records to {OUTPUT_PATH}")

    lines = [
        "# Review flags",
        "",
        f"Generated (not API-sourced) descriptions: {len(generated_flags)}",
        f"Missing covers: {len(no_cover_flags)}",
        "",
        "## Generated descriptions (check tone/accuracy)",
        "",
    ]
    for r in generated_flags:
        lines.append(f"- **{r['book']}** by {r['author_display']} — _{r['description']}_")
    lines += ["", "## Missing covers", ""]
    for r in no_cover_flags:
        lines.append(f"- {r['book']} by {r['author_display']}")

    REVIEW_PATH.write_text("\n".join(lines))
    print(f"Wrote review flags to {REVIEW_PATH}")

    countries = {r["country"] for r in enriched if r["country"]}
    print(f"Distinct countries: {len(countries)}")


if __name__ == "__main__":
    main()
