"""Polite cached HTTP fetching shared by the scrapers."""
import hashlib
import pathlib
import re
import threading
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; BaysideFlooringCatalogue/1.0)"
_lock = threading.Lock()
_last = [0.0]
DELAY = 0.25  # seconds between requests, across all threads


def _throttle():
    with _lock:
        wait = _last[0] + DELAY - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def get(url, cache_dir, binary=False, retries=3):
    cache = pathlib.Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()
    path = cache / key
    if path.exists():
        data = path.read_bytes()
        return data if binary else data.decode("utf8", "replace")
    last = None
    for attempt in range(retries):
        try:
            _throttle()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            path.write_bytes(data)
            return data if binary else data.decode("utf8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed {url}: {last}")


def locs(xml):
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
