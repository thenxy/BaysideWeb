#!/usr/bin/env python3
"""Build src/products/*.md and src/img/products/* from supplier websites.

Usage: python3 scripts/scrape.py [--cache DIR] [--no-images] [--only jims|flooringlab|everfloor]

Re-run any time to refresh the catalogue. Generated files carry `source:`
in their front matter, so hand-written products (no `source`) are never touched.
"""
import argparse
import html
import io
import json
import pathlib
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import yaml
from bs4 import BeautifulSoup
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fetch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "src" / "products"
IMG = ROOT / "src" / "img" / "products"
MAX_IMAGES = 2
IMG_WIDTH = 800

JIMS_CATEGORY = {
    "Hybrid Flooring": ("hybrid", None),
    "Laminate Flooring": ("laminate", None),
    "Timber Flooring": ("timber", None),
    "Vinyl Flooring": ("vinyl", None),
    "Carpets": ("carpet", None),
    "Nylon": ("carpet", "Nylon"),
    "Polyester": ("carpet", "Polyester"),
    "Wool": ("carpet", "Wool"),
    "Carpet Tiles": ("carpet", "Carpet tiles"),
    "Underlay": ("accessories", "Underlay"),
    "Carpetmate Standard": ("accessories", "Underlay"),
    "Government Red": ("accessories", "Underlay"),
    "Eureka": ("accessories", "Underlay"),
    "Supergreen": ("accessories", "Underlay"),
    "Renu": ("accessories", "Underlay"),
    "Flooring Accessories": ("accessories", "Trims"),
    "Scotia": ("accessories", "Trims"),
    "Cover trim": ("accessories", "Trims"),
    "L Trim": ("accessories", "Trims"),
    "C channel": ("accessories", "Trims"),
}
EVER_TOP = {
    "Timber Flooring": "timber", "Vinyl Flooring": "vinyl", "Hybrid Flooring": "hybrid",
    "Bamboo Flooring": "bamboo", "Laminate Flooring": "laminate",
}
# category pages missing from Everfloor's menu
EVER_EXTRA = {
    "adhesives": "accessories", "floor-preparation": "accessories",
    "flooring-trims": "accessories", "water-resistant-scotia": "accessories",
    "marvel-pro-herringbone": "hybrid", "woodveneer-oak": "timber",
}


def slugify(s):
    s = html.unescape(s).lower().replace("&", " and ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def short(text, sentences=2, limit=420):
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:sentences])
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


def thickness_of(*texts):
    for t in texts:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mm", t or "")
        if m:
            return m.group(1) + "mm"
    return None


def ld_product(h):
    for x in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        try:
            j = json.loads(x)
        except ValueError:
            continue
        for n in (j.get("@graph") or [j]):
            if n.get("@type") == "Product":
                return n
    return {}


# ---------------------------------------------------------------- Jim's
def scrape_jims(cache):
    base = "https://jimsflooring.com.au"
    urls = fetch.locs(fetch.get(base + "/sitemap-products.xml", cache))
    out = []
    for u in urls:
        h = fetch.get(u, cache)
        ld = ld_product(h)
        s = BeautifulSoup(h, "lxml")
        h1 = s.find("h1")
        name = html.unescape((h1.get_text(strip=True) if h1 else ld.get("name", ""))).strip()
        name = re.sub(r"^AAA\s+", "", name)
        cat, sub = JIMS_CATEGORY.get(ld.get("category"), (None, None))
        if not cat:
            print("  ! unmapped Jim's category", ld.get("category"), u)
            continue
        brand = "Jim's"
        m = re.match(r"^([A-Za-z][A-Za-z' ]{2,24}):\s+(.+)$", name)
        if m:
            brand, name = m.group(1).strip().title(), m.group(2).strip()
        sku = re.search(r'product-sku">\s*SKU:\s*([^<]+)<', h)
        short_desc = s.find(class_="product-short-description")
        specs = {}
        for tr in s.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) == 2 and tds[0] and tds[1] and tds[0].lower() not in ("product name", "specification"):
                specs[tds[0]] = tds[1]
        colours = []
        for im in s.select("img.product-thumb"):
            v = im.get("data-variant")
            if v and v not in colours:
                colours.append(v)
        images = [urllib.parse.urljoin(base, i) for i in (ld.get("image") or [])]
        out.append(dict(
            title=name, brand=brand, range=None, category=cat, subcategory=sub,
            sku=sku.group(1).strip() if sku else None,
            thickness=thickness_of(specs.get("Dimensions"), specs.get("Thickness"), name),
            colours=colours or None, specs=specs or None,
            desc=short(short_desc.get_text(" ") if short_desc else ld.get("description", "")),
            images=images, source=u, supplier="Jim's Flooring",
        ))
    return out


# ------------------------------------------------------ The Flooring Lab
FL_KEYS = ["Dimensions", "Wear Layer", "Substrate", "Backing", "Edge", "Surface", "Coating",
           "Installation", "Coverage", "Boards", "Residential Warranty"]
FL_RANGES = {"phoenix": "7", "lumina": "9"}  # range -> required thickness (mm)


def scrape_flooringlab(cache):
    base = "https://theflooringlab.com.au"
    urls = [u for u in fetch.locs(fetch.get(base + "/sitemap.xml", cache))
            if re.search(r"/colours/(phoenix|lumina)-", u)]
    out = []
    for u in urls:
        h = fetch.get(u, cache)
        ld = ld_product(h)
        rng = u.rsplit("/", 1)[1].split("-", 1)[0]
        name = re.split(r"\s+[–-]\s+", html.unescape(ld.get("name", "")))[0].strip()
        lines = [l.strip() for l in BeautifulSoup(h, "lxml").get_text("\n").split("\n") if l.strip()]
        specs = {}
        start = next((i for i in range(len(lines) - 1) if lines[i] == "Dimensions" and "×" in lines[i + 1]), 0)
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("View & Download")), len(lines))
        seg = lines[start:end]
        for i, l in enumerate(seg):
            if l in FL_KEYS and l not in specs and i + 1 < len(seg):
                specs[l] = seg[i + 1]
        dims = specs.get("Dimensions", "")
        t = thickness_of(dims)
        if not dims or not t or t[:-2] != FL_RANGES[rng]:
            print(f"  ! skipping {u}: thickness {t} not {FL_RANGES[rng]}mm")
            continue
        rname = rng.title()
        out.append(dict(
            title=name, brand="The Flooring Lab", range=f"{rname} {t} Hybrid", category="hybrid",
            subcategory=None, sku=ld.get("sku"), thickness=t, colours=None, specs=specs,
            desc=f"{name} from the {rname} collection: a {t} hybrid plank with a "
                 f"{specs.get('Wear Layer', '0.5 mm').replace(' ', '')} wear layer and a "
                 f"{re.sub(r'(?i)\s*years?$', '', specs.get('Residential Warranty', '25 years'))}-year residential warranty.",
            images=[ld["image"]] if ld.get("image") else [], source=u, supplier="The Flooring Lab",
        ))
    return out


# -------------------------------------------------------------- Everfloor
def scrape_everfloor(cache):
    base = "https://everfloor.com.au"
    sm = fetch.locs(fetch.get(base + "/sitemap.xml", cache))
    nav = BeautifulSoup(fetch.get(base + "/engineered-flooring", cache), "lxml")
    cat_of, range_name = dict(EVER_EXTRA), {}
    for wrap in nav.select(".category-wrapper"):
        head = wrap.select_one(".heading-style-h4")
        top = EVER_TOP.get(head.get_text(strip=True)) if head else None
        for a in wrap.select('a.open-menu_link[href^="/category/"]'):
            slug = a["href"].rsplit("/", 1)[1]
            if top:
                cat_of[slug] = top
            range_name[slug] = a.get_text(strip=True)
    prod_cat, prod_range = {}, {}
    for cu in [u for u in sm if "/category/" in u]:
        slug = cu.rsplit("/", 1)[1]
        page = fetch.get(cu, cache)
        if slug not in range_name:
            h1 = BeautifulSoup(page, "lxml").find("h1")
            range_name[slug] = h1.get_text(strip=True) if h1 else slug.replace("-", " ").title()
        for p in set(re.findall(r'href="/product/([^"]+)"', page)):
            prod_cat[p] = cat_of.get(slug, "accessories")
            prod_range[p] = range_name[slug]
    out = []
    for u in [u for u in sm if "/product/" in u]:
        slug = u.rsplit("/", 1)[1]
        h = fetch.get(u, cache)
        s = BeautifulSoup(h, "lxml")
        h1 = s.find("h1")
        colour = h1.get_text(strip=True) if h1 else (s.title.string or slug)
        specs = {}
        for k in s.select("p.product-details"):
            v = k.find_next_sibling("p", class_="details-specs")
            if v and k.get_text(strip=True) and v.get_text(strip=True):
                specs.setdefault(k.get_text(strip=True), v.get_text(" ", strip=True))
        norm = lambda x: re.sub(r"[^a-z0-9]", "", urllib.parse.unquote(x).lower())  # noqa: E731
        key = norm(colour)
        imgs, seen = [], set()
        for im in s.find_all("img"):
            src = im.get("src", "")
            if not src.startswith("http") or not re.search(r"\.(jpe?g|png|webp)$", src, re.I):
                continue
            fn = src.rsplit("/", 1)[1]
            if key and key in norm(fn) and "-p-" not in fn and fn not in seen:
                seen.add(fn)
                imgs.append(src)
        if not imgs and h1:  # own image shown twice (main + zoom) while "related" ones appear once
            after = [i.get("src", "") for i in h1.find_all_next("img")
                     if re.search(r"\.(jpe?g|png|webp)$", i.get("src", ""), re.I) and "EF%20Sample" not in i.get("src", "")]
            imgs = [u for u in dict.fromkeys(after) if after.count(u) >= 2][:MAX_IMAGES]
        title_tag = (s.title.string or "").strip()
        if "coming soon" in colour.lower():
            continue
        cat = prod_cat.get(slug)
        rng = prod_range.get(slug)
        if not cat:  # not listed on any category page: infer from the product title
            low = (title_tag + " " + slug).lower()
            cat = next((c for w, c in (("bamboo", "bamboo"), ("laminate", "laminate"), ("hybrid", "hybrid"),
                                       ("vinyl", "vinyl"), ("timber", "timber"), ("oak", "timber"))
                        if w in low), "accessories")
            rng = re.sub(r"\s+-\s+.*$", "", title_tag) if cat != "accessories" else "Flooring Trims"
        rng = re.sub(r"\s+", " ", rng or "").strip()
        bits = [specs.get("Finish"), specs.get("Size")]
        desc = f"{colour} from the {rng} range"
        desc += (": " + ", ".join(b for b in bits if b) + ".") if any(bits) else "."
        if specs.get("Warranty"):
            w = re.sub(r"(?i)\s*years?$", "", specs["Warranty"]).strip()
            desc += f" {w}-year warranty." if w.isdigit() else f" Warranty: {specs['Warranty']}."
        out.append(dict(
            title=colour, brand="Everfloor", range=rng,
            category=cat, subcategory=None, sku=None,
            thickness=thickness_of(specs.get("Size"), rng, title_tag),
            colours=None, specs=specs or None, desc=desc, images=imgs, source=u,
            supplier="Everfloor",
        ))
    return out


# ----------------------------------------------------------------- output
def save_image(url, dest, cache):
    if dest.exists():
        return True
    try:
        raw = fetch.get(url, cache, binary=True)
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        if im.width > IMG_WIDTH:
            im = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "WEBP", quality=72, method=6)
        return True
    except Exception as e:  # noqa: BLE001
        print("  ! image failed", url, e)
        return False


def tidy(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t.title() if len(t) > 3 and t.isupper() else t


def write_product(p, slugs, cache, images=True):
    p["title"], p["range"] = tidy(p["title"]), tidy(p["range"]) or None
    base = slugify(f"{p['brand']} {p['range'] or ''} {p['title']}")
    slug, n = base, 2
    while slug in slugs:
        slug = f"{base}-{n}"
        n += 1
    slugs.add(slug)
    saved = []
    if images:
        for i, url in enumerate(p["images"][:MAX_IMAGES]):
            name = f"{slug}.webp" if i == 0 else f"{slug}-{i + 1}.webp"
            if save_image(url, IMG / name, cache):
                saved.append(f"/img/products/{name}")
    fm = {"title": p["title"], "brand": p["brand"], "category": p["category"]}
    for k in ("range", "subcategory", "sku", "thickness", "colours"):
        if p.get(k):
            fm[k] = p[k]
    if saved:
        fm["image"] = saved[0]
        if len(saved) > 1:
            fm["gallery"] = saved[1:]
    if p.get("specs"):
        fm["specs"] = p["specs"]
    fm["supplier"] = p["supplier"]
    fm["source"] = p["source"]
    text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=100) + "---\n"
    text += (p.get("desc") or "") + "\n"
    (PRODUCTS / f"{slug}.md").write_text(text, encoding="utf8")
    return slug


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".scrape-cache"))
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--only", choices=["jims", "flooringlab", "everfloor"])
    a = ap.parse_args()
    jobs = {"jims": scrape_jims, "flooringlab": scrape_flooringlab, "everfloor": scrape_everfloor}
    products = []
    for name, fn in jobs.items():
        if a.only and a.only != name:
            continue
        print("scraping", name, flush=True)
        got = fn(a.cache)
        print(f"  {len(got)} products", flush=True)
        products += got
    # remove previously generated products (those with a `source:`), keep hand-written ones
    PRODUCTS.mkdir(parents=True, exist_ok=True)
    hosts = {"jims": "jimsflooring.com.au", "flooringlab": "theflooringlab.com.au", "everfloor": "everfloor.com.au"}
    for f in PRODUCTS.glob("*.md"):
        m = re.search(r"^source: https?://([^/\s]+)", f.read_text(encoding="utf8"), re.M)
        if m and (not a.only or m.group(1) == hosts[a.only]):
            f.unlink()
    slugs = {f.stem for f in PRODUCTS.glob("*.md")}
    for p in products:
        write_product(p, slugs, a.cache, not a.no_images)
    print("wrote", len(products), "products")


if __name__ == "__main__":
    main()
