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
IMG_WIDTH = 1000
THUMB_WIDTH = 480

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
        colours = {}
        for im in s.select("img.product-thumb"):
            nm = clean_variant(im.get("data-variant"))
            src = im.get("data-full-src") or im.get("src")
            if nm and src:
                full = urllib.parse.urljoin(base, src)
                colours.setdefault(nm, []).append([re.sub(r"-\d+x\d+(?=\.\w+$)", "", full), full])
        images = [[urllib.parse.urljoin(base, i)] for i in (ld.get("image") or [])]
        out.append(dict(
            title=name, category=cat, subcategory=sub,
            thickness=thickness_of(name, specs.get("Dimensions"), specs.get("Thickness")),
            colours=[dict(name=n, images=[v[0]]) for n, v in colours.items()] or None,
            specs=specs or None,
            desc=short(short_desc.get_text(" ") if short_desc else ld.get("description", "")),
            images=images, source=u, supplier="Jim's Flooring",
        ))
    return out


JUNK_TOKEN = re.compile(
    r"^(?:\d+p?|\d+x\d*\w*|[a-z]|swatch|lo|hi|res|lr|hr|web|ok|scaled|\d?sm|z|k|gf|pdf|hn\d+\w*|(?=[0-9a-f]*\d)[0-9a-f]{3,})$",
    re.I)


def clean_variant(v):
    """Colour names come from image file names; drop spec-sheet / montage / code-only entries."""
    v = re.sub(r"\s+", " ", v or "").strip()
    if (not v or re.search(r"spec|brochure|pdf|data ?sheet|swatch card", v, re.I) or re.match(r"^\d+[A-Za-z]+\d", v)
            or re.match(r"^(?:img|image|dsc|photo|screenshot)\b", v, re.I)):
        return None
    toks = []
    for t in v.split():
        t = re.sub(r"(?i)^(?:armstrong|floortex|dunlop|jims)(?=[a-z])", "", t)  # brand glued to a word
        t = re.sub(r"^20(?=[A-Za-z])", "", t)  # "%20" left over from a URL-encoded space
        if t and not JUNK_TOKEN.match(t):
            toks.append(t[0].upper() + t[1:] if t.islower() else t)
    v = scrub(" ".join(toks))
    return v if len(v) > 1 else None


# ------------------------------------------------------ The Flooring Lab
FL_KEYS = ["Dimensions", "Wear Layer", "Substrate", "Backing", "Edge", "Surface", "Coating",
           "Installation", "Coverage", "Boards", "Residential Warranty"]
FL_RANGES = {"phoenix": "7", "lumina": "9"}  # range -> required thickness (mm)


def scrape_flooringlab(cache):
    base = "https://theflooringlab.com.au"
    urls = [u for u in fetch.locs(fetch.get(base + "/sitemap.xml", cache))
            if re.search(r"/colours/(phoenix|lumina)-", u)]
    groups = {}
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
        g = groups.setdefault(rng, dict(title=f"{rng.title()} {t} Hybrid", category="hybrid", subcategory=None,
                                        thickness=t, specs=specs, colours=[], images=[], source=base + f"/collections/{rng}",
                                        supplier="The Flooring Lab"))
        g["colours"].append(dict(name=name, images=[ld["image"]] if ld.get("image") else []))
    out = []
    for g in groups.values():
        sp = g["specs"]
        w = re.sub(r"(?i)\s*years?$", "", sp.get("Residential Warranty", "25 years"))
        g["desc"] = (f"A {g['thickness']} hybrid plank in {len(g['colours'])} colours, with a "
                     f"{sp.get('Wear Layer', '0.5 mm').replace(' ', '')} wear layer and a {w}-year residential warranty.")
        out.append(g)
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
    groups = {}
    rkey = lambda r: " ".join(sorted(t for t in re.findall(r"[a-z0-9.]+", r.lower().replace("-", " "))  # noqa: E731
                                     if t not in ("laminate", "flooring")))
    for u in [u for u in sm if "/product/" in u]:
        slug = u.rsplit("/", 1)[1]
        h = fetch.get(u, cache)
        s = BeautifulSoup(h, "lxml")
        h1 = s.find("h1")
        colour = h1.get_text(strip=True) if h1 else (s.title.string or slug)
        if "coming soon" in colour.lower():
            continue
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
            imgs = [x for x in dict.fromkeys(after) if after.count(x) >= 2][:1]
        title_tag = (s.title.string or "").strip()
        cat = prod_cat.get(slug)
        rng = prod_range.get(slug)
        if not cat:  # not listed on any category page: infer from the product title
            low = (title_tag + " " + slug).lower()
            cat = next((c for w, c in (("bamboo", "bamboo"), ("laminate", "laminate"), ("hybrid", "hybrid"),
                                       ("vinyl", "vinyl"), ("timber", "timber"), ("oak", "timber"))
                        if w in low), "accessories")
            rng = re.sub(r"\s+-\s+.*$", "", title_tag) if cat != "accessories" else "Flooring Trims"
        rng = re.sub(r"\s+", " ", rng or "").strip()
        g = groups.get(rkey(rng))
        if g is None:
            g = groups[rkey(rng)] = dict(title=rng, category=cat, subcategory=None, colours=[], images=[],
                                         source=u, supplier="Everfloor", _specs=[])
        g["colours"].append(dict(name=colour, images=imgs[:1], _specs=specs))
    out = []
    for g in groups.values():
        cols = g["colours"]
        allspecs = [c.pop("_specs") for c in cols]
        keys = list(dict.fromkeys(k for sp in allspecs for k in sp))
        common = {k: allspecs[0][k] for k in keys
                  if all(sp.get(k) == allspecs[0].get(k) for sp in allspecs) and k in allspecs[0]}
        for c, sp in zip(cols, allspecs):
            diff = {k: v for k, v in sp.items() if k not in common}
            if diff:
                c["specs"] = diff
        g["specs"] = common or None
        g.pop("_specs", None)
        g["thickness"] = thickness_of(common.get("Size"), g["title"], *(sp.get("Size") for sp in allspecs))
        bits = [common.get("Finish")]
        g["desc"] = f"{g['title']} is available in {len(cols)} colour{'s' if len(cols) != 1 else ''}." + (
            f" Finish: {common['Finish']}." if common.get("Finish") else "")
        if common.get("Warranty"):
            w = re.sub(r"(?i)\s*years?$", "", common["Warranty"]).strip()
            g["desc"] += f" {w}-year warranty." if w.isdigit() else f" Warranty: {common['Warranty']}."
        out.append(g)
    return out


# ----------------------------------------------------------------- output
def save_image(urls, dest, cache):
    """Save a large version (dest) and a small grid/swatch version (<name>-t.webp)."""
    thumb = dest.with_name(dest.stem + "-t.webp")
    if dest.exists() and thumb.exists():
        return True
    last = None
    for url in ([urls] if isinstance(urls, str) else urls):
        try:
            raw = fetch.get(url, cache, binary=True)
            im = Image.open(io.BytesIO(raw))
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            for path, width, q in ((dest, IMG_WIDTH, 76), (thumb, THUMB_WIDTH, 70)):
                out = im
                if im.width > width:
                    out = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
                out.save(path, "WEBP", quality=q, method=4)
            return True
        except Exception as e:  # noqa: BLE001
            last = e
    print("  ! image failed", urls, last)
    return False


# Company names that must never appear on the public site.
SCRUB = re.compile(
    r"\b(?:the\s+flooring\s+lab|flooring\s+lab|jim['’]?s|jims|everfloor|floortex|armstrong|dunlop|"
    r"tudorwoods|carpetmate|continental\s+oak)(?![a-z])['’]?s?\s*", re.I)


def scrub(t):
    t = SCRUB.sub(" ", t or "")
    t = re.sub(r"\s*:\s*", " - ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^[\s\-–,;]+|[\s\-–,;]+$", "", t)
    return re.sub(r"(?:\s-){2,}", " -", t)


def tidy(t):
    t = scrub(t)
    if len(t) > 3 and t.isupper():
        return t.title()
    return re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group().title(), t)


UNCONFIRMED = re.compile(r"to be (?:confirmed|advised|announced)|\btbc\b|\btba\b|coming soon|^\W*(?:n/?a|-+|tbd)\W*$", re.I)


def scrub_text(t):
    """Like scrub() but keeps sentence punctuation intact."""
    t = SCRUB.sub(" ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def clean_specs(sp):
    out = {}
    for k, v in (sp or {}).items():
        v = scrub_text(str(v))
        if v and not UNCONFIRMED.search(v):
            out[k] = v
    return out


def write_product(p, slugs, cache, images=True):
    p["title"] = tidy(p["title"])
    p["desc"] = scrub_text(p.get("desc"))
    p["specs"] = clean_specs(p.get("specs"))
    if p.get("thickness") and UNCONFIRMED.search(str(p["thickness"])):
        p["thickness"] = None
    base = slugify(p["title"])
    slug, n = base, 2
    while slug in slugs:
        slug = f"{base}-{n}"
        n += 1
    slugs.add(slug)
    colours, used = [], set()
    for c in p.get("colours") or []:
        name = tidy(c["name"])
        if name.lower().startswith(p["title"].lower() + " "):  # drop a repeated product-line prefix
            name = name[len(p["title"]) + 1:]
        if not name:
            continue
        cs = slugify(name) or "colour"
        while cs in used:
            cs += "-x"
        used.add(cs)
        entry = {"name": name}
        if images and c.get("images"):
            fn = f"{slug}-{cs}.webp"
            if save_image(c["images"][0], IMG / fn, cache):
                entry["image"] = f"/img/products/{fn}"
        sp = clean_specs(c.get("specs"))
        if sp:
            entry["specs"] = sp
        colours.append(entry)
    fm = {"title": p["title"], "category": p["category"]}
    for k in ("subcategory", "thickness"):
        if p.get(k):
            fm[k] = p[k]
    if len(colours) > 1:
        fm["colours"] = colours
        first = next((c["image"] for c in colours if c.get("image")), None)
        if first:
            fm["image"] = first
    else:
        saved = []
        imgs = [c for c in (p.get("images") or [])] or [[u] for c in (p.get("colours") or []) for u in c.get("images", [])]
        if images:
            for i, urls in enumerate(imgs[:3]):
                fn = f"{slug}.webp" if i == 0 else f"{slug}-{i + 1}.webp"
                if save_image(urls, IMG / fn, cache):
                    saved.append(f"/img/products/{fn}")
        if saved:
            fm["image"] = saved[0]
            if len(saved) > 1:
                fm["gallery"] = saved[1:]
    if p["specs"]:
        fm["specs"] = p["specs"]
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
    # accessories are not sold online; wall coverings are out of scope for a flooring catalogue
    products = [p for p in products if p["category"] != "accessories" and "wall covering" not in
                (p["title"] + " " + (p.get("desc") or "")).lower()[:400]]
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
    used = set()
    for f in PRODUCTS.glob("*.md"):
        used |= set(re.findall(r"/img/products/([^\s]+\.webp)", f.read_text(encoding="utf8")))
    for im in IMG.glob("*.webp"):
        if re.sub(r"-t\.webp$", ".webp", im.name) not in used:
            im.unlink()
    print("wrote", len(products), "products")


if __name__ == "__main__":
    main()
