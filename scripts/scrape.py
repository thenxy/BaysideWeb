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
    "Carpets": ("carpet", "Other"),
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
    "marvel-pro-herringbone": "vinyl",
}
# listed on a category page but really part of another range: let the matching step place them
EVER_UNGROUPED = {"woodveneer-oak"}
# the page called "Marvel Pro Herringbone" is the 5mm vinyl herringbone range
EVER_RENAME = {"marvel-pro-herringbone": "Marvel Vinyl Herringbone"}


def slugify(s):
    s = html.unescape(s).lower().replace("&", " and ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def plain(text):
    """Strip any HTML (some supplier fields contain escaped markup) and tidy whitespace."""
    t = BeautifulSoup(html.unescape(text or ""), "lxml").get_text(" ")
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"^(?:Description|Overview|Product Description)\b[:\s-]*", "", t).strip()


def short(text, sentences=2, limit=420):
    text = plain(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    if text.endswith("…") and len(parts) > 1:  # supplier text already cut off mid-sentence: keep whole sentences
        parts = parts[:-1]
    out = ""
    for part in parts[:sentences]:
        if out and len(out) + 1 + len(part) > limit:
            break
        out = (out + " " + part).strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if out.endswith("…"):  # never end on a cut-off fragment: fall back to the last complete sentence/clause
        body = out[:-1].rstrip()
        cut = max(body.rfind("."), body.rfind("!"), body.rfind("?"))
        if cut > 40:
            out = body[:cut + 1]
        elif "," in body:
            out = body[:body.rfind(",")].rstrip() + "."
        else:
            out = body + "."
    return out


SPEC_LABEL = re.compile(r"(Type Of Product|Pile Material|Pile Height|Pile Weight|Wear Warranty|Warranty|Backing|Dye Method|Construction|Width):\s*")


def spec_dump(text):
    """'Type Of Product: Loop pile Pile Material: 100% wool ...' -> dict, or None when it is normal prose."""
    t = plain(text)
    m = list(SPEC_LABEL.finditer(t))
    if len(m) < 2 or m[0].start() > 3:
        return None
    out = {}
    for i, x in enumerate(m):
        end = m[i + 1].start() if i + 1 < len(m) else len(t)
        out[x.group(1)] = t[x.end():end].strip(" .")
    return out


def thickness_of(*texts):
    """Nominal thickness: '10mm Name', 'W x L x 12mm', or the 15 of '15/4' (total / wear layer).
    Anything over 40mm is a plank width or length, not a thickness."""
    def fmt(n):
        v = float(n)
        return None if v <= 0 or v > 40 else (f"{v:g}") + "mm"

    for t in texts:
        t = t or ""
        m = re.search(r"\d+(?:\.\d+)?\s*(?:mm)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", t, re.I)
        for m in ([m] if m else []) + list(re.finditer(r"(?<![/\d.])(\d+(?:\.\d+)?)\s*mm", t, re.I)) + \
                list(re.finditer(r"\b(\d{2})/\d(?!\d)", t)):
            r = fmt(m.group(1))
            if r:
                return r
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
            thickness=thickness_of(name, specs.get("Dimensions"), *[v for k, v in specs.items() if "thickness" in k.lower()],
                                 re.sub(r"(?i).*thickness\W*", "", short_desc.get_text(" ") if short_desc else "", count=1)[:40]),
            colours=[dict(name=n, images=v) for n, v in colours.items()] or None,
            specs=specs or None,
            desc=short(short_desc.get_text(" ") if short_desc else ld.get("description", "")),
            raw_desc=short_desc.get_text(" ") if short_desc else ld.get("description", ""),
            images=images, source=u, supplier="Jim's Flooring",
        ))
    return out


JUNK_TOKEN = re.compile(
    r"^(?:web\d*|swatch\w*|\d+p?|\d+x\d*\w*|[a-z]|swatch|lo|hi|res|lr|hr|web|ok|scaled|\d?sm|z|k|gf|pdf|hn\d+\w*|(?=[0-9a-f]*\d)[0-9a-f]{3,})$",
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
        if slug in EVER_UNGROUPED:
            continue
        for p in set(re.findall(r'href="/product/([^"]+)"', page)):
            prod_cat[p] = cat_of.get(slug, "accessories")
            prod_range[p] = EVER_RENAME.get(slug, range_name[slug])
    groups = {}
    rkey = lambda r: " ".join(sorted(t for t in re.findall(r"[a-z0-9.]+", r.lower().replace("-", " "))  # noqa: E731
                                     if t not in ("laminate", "flooring")))
    entries = []
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
            if re.search(r"angle|cover|end-?cap|border|scotia|trim|adhesive|primer|stopgap|nosing|reducer|threshold", slug):
                cat = "accessories"
            else:
                cat = next((c for w, c in (("bamboo", "bamboo"), ("laminate", "laminate"), ("hybrid", "hybrid"),
                                           ("vinyl", "vinyl"), ("timber", "timber"), ("oak", "timber"))
                            if w in low), "accessories")
            rng = re.sub(r"\s+-\s+.*$", "", title_tag) if cat != "accessories" else "Flooring Trims"
        rng = re.sub(r"\s+", " ", rng or "").strip()
        entries.append(dict(colour=colour, specs=specs, imgs=imgs[:1], cat=cat, rng=rng,
                            mapped=slug in prod_cat, slug=slug, url=u))
    toks = lambda r: set(re.findall(r"[a-z0-9.]+", r.lower().replace("-", " "))) - {"laminate", "flooring"}  # noqa: E731
    nonnum = lambda t: {x for x in t if not re.match(r"^[\d./]+(?:mm)?$", x)}  # noqa: E731
    for e in sorted(entries, key=lambda e: not e["mapped"]):  # listed products first, then the stragglers
        k = rkey(e["rng"])
        g = groups.get(k)
        if g is None and not e["mapped"] and e["cat"] != "accessories":
            # a product missing from the category pages: attach it to the range it obviously belongs to
            T = toks(e["rng"])
            cands = [x for x in groups.values() if len(T) >= 2 and T < x["_tok"] and x["category"] != "accessories"]
            if len(cands) != 1:
                S = toks(e["slug"])
                cands = [x for x in groups.values() if x["category"] != "accessories"
                         and nonnum(x["_tok"]) and nonnum(x["_tok"]) <= S]
                best = max((len(nonnum(x["_tok"])) for x in cands), default=0)
                cands = [x for x in cands if len(nonnum(x["_tok"])) == best]
            if len(cands) == 1:
                g = cands[0]
        if g is None:
            g = groups[k] = dict(title=e["rng"], category=e["cat"], subcategory=None, colours=[], images=[],
                                 source=e["url"], supplier="Everfloor", _tok=toks(e["rng"]))
        g["colours"].append(dict(name=e["colour"], images=e["imgs"], _specs=e["specs"]))
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
        g.pop("_tok", None)
        g["thickness"] = thickness_of(g["title"], common.get("Size"), *(sp.get("Size") for sp in allspecs))
        bits = [common.get("Finish")]
        g["desc"] = f"{g['title']} is available in {len(cols)} colour{'s' if len(cols) != 1 else ''}." + (
            f" Finish: {common['Finish']}." if common.get("Finish") else "")
        if common.get("Warranty"):
            w = re.sub(r"(?i)\s*years?$", "", common["Warranty"]).strip()
            g["desc"] += f" {w}-year warranty." if w.isdigit() else f" Warranty: {common['Warranty']}."
        out.append(g)
    return out


# ----------------------------------------------------------------- output
def as_groups(x):
    """Candidate photos for one picture: a list of groups, each a list of alternative URLs for the same file."""
    x = [x] if isinstance(x, str) else list(x)
    return [[e] if isinstance(e, str) else list(e) for e in x]


def best_image(groups, cache):
    """The widest photo among the candidates (suppliers often list a tiny swatch and a large room photo)."""
    best = None
    for g in groups:
        for url in g:
            try:
                im = Image.open(io.BytesIO(fetch.get(url, cache, binary=True)))
                im.load()
            except Exception:  # noqa: BLE001
                continue
            if best is None or im.width > best.width:
                best = im
            break  # first alternative that loads
        if best is not None and best.width >= 900:
            break
    return best


def width_of(path):
    try:
        with Image.open(path) as im:
            return im.width
    except Exception:  # noqa: BLE001
        return 0


def save_image(groups, dest, cache):
    """Save a large version (dest) and a small grid/swatch version (<name>-t.webp)."""
    groups = as_groups(groups)
    thumb = dest.with_name(dest.stem + "-t.webp")
    if dest.exists() and thumb.exists() and (len(groups) == 1 or width_of(dest) >= 640):
        return True
    im = best_image(groups, cache)
    if im is None:
        print("  ! image failed", groups[:1])
        return False
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for path, width, q in ((dest, IMG_WIDTH, 76), (thumb, THUMB_WIDTH, 70)):
        out = im
        if im.width > width:
            out = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        out.save(path, "WEBP", quality=q, method=4)
    return True


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
    t = re.sub(r"\b[a-z]{3,}\b", lambda m: m.group().capitalize(), t)  # "Oak hybrid" -> "Oak Hybrid"
    if len(t) > 3 and t.isupper():
        return t.title()
    return re.sub(r"\b[A-Z]{4,}\b", lambda m: m.group().title(), t)


UNCONFIRMED = re.compile(r"to be (?:confirmed|advised|announced)|\btbc\b|\btba\b|coming soon|^\W*(?:n/?a|-+|tbd)\W*$", re.I)


def scrub_text(t):
    """Like scrub() but keeps sentence punctuation intact."""
    t = SCRUB.sub(" ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def norm_spec(k, v):
    k = re.sub(r"\s+", " ", str(k)).strip()
    if re.fullmatch(r"\d{4,}", k):  # colour-code rows (835701: Platinum Haze) are ordering codes, not specs
        return None, None
    k = re.sub(r"\b([a-z])", lambda m: m.group(1).upper(), k)
    v = scrub_text(str(v))
    v = re.sub(r"(\d)\s?(?:㎡|m2|sqm)\b", r"\1 m²", v, flags=re.I)
    v = re.sub(r"㎡|\bsqm\b", "m²", v, flags=re.I)
    v = re.sub(r"(?<=[\dm])\s+x\s+(?=\d)", " × ", v)
    v = re.sub(r"(\d)\s*Years?\b", lambda m: m.group(1) + (" year" if m.group(1) == "1" else " years"), v)
    return k, v


def clean_specs(sp):
    out = {}
    for k, v in (sp or {}).items():
        k, v = norm_spec(k, v)
        if k and v and not UNCONFIRMED.search(v):
            out[k] = v
    return out


# Categories the business sells (bamboo and accessories are deliberately left out).
SOLD = {"hybrid", "timber", "laminate", "vinyl", "carpet"}

MM = re.compile(r"\s*(?<![/\d.])\b\d+(?:\.\d+)?\s?mm\b", re.I)


def strip_mm(t, thickness=None):
    """Thickness is shown as its own sub-heading, so take it out of the name."""
    out = re.sub(r"(\d/\d+)\s?mm\b", r"\1", t, flags=re.I)  # 15/4mm -> 15/4 (a build, not a thickness)
    out = MM.sub("", out)
    num = (thickness or "").replace("mm", "")
    if num:
        out = re.sub(r"\s+" + re.escape(num) + r"$", "", out)  # trailing bare "6.5"
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"^[\s\-–,;]+|[\s\-–,;]+$", "", out)
    out = re.sub(r"\s+-\s+-\s+", " - ", out)
    return out if len(out) > 2 else t


def colour_name(name, orig, title):
    name = tidy(name)
    for pre in (orig, title):
        if name.lower().startswith(pre.lower() + " "):  # drop a repeated product-line prefix
            name = name[len(pre) + 1:]
            break
    words = {re.sub(r"\d+$", "", w.lower()) for w in re.findall(r"[A-Za-z0-9]+", orig)}
    toks = name.split()
    if len(toks) > 1 and re.sub(r"\d+$", "", toks[0].lower()) in words:  # "Accolade2 Kiama" -> "Kiama"
        name = " ".join(toks[1:])
    name = re.sub(r"^\d+/\d+\s+", "", name)
    name = re.sub(r"\b([A-Za-z]{1,3})(\d{3,})([A-Za-z]?)\b", lambda m: (m[1] + m[2] + m[3]).upper(), name)
    name = re.sub(r"([a-z])(\d{3,})", r"\1 \2", name)
    name = re.sub(r"(?<=[A-Za-z])\d{1,2}\b", "", name)      # "Paris Natural Oak1" -> "Paris Natural Oak"
    name = re.sub(r"\b\d+(?=[A-Za-z])", "", name)           # "9Crushedice" -> "Crushedice"
    name = re.sub(r"\s+", " ", name).strip()
    if name.lower() == "spg":
        name = "Spotted Gum"
    elif len(name) <= 3 and name.isalpha() and not re.search(r"[aeiou]", name, re.I):
        name = name.upper()                                   # "Mcg" -> "MCG"
    return name


def write_product(p, slugs, cache, images=True):
    orig = tidy(p["title"]).replace("Natrails", "Natralis")
    p["title"] = strip_mm(orig, p.get("thickness"))
    p["specs"] = clean_specs(p.get("specs"))
    p["desc"] = re.sub(r"\bSDN\b", "Solution-dyed nylon", scrub_text(p.get("desc")))
    if re.search(r"Technical Specifications|\b[A-Z][a-z]+:\s", p["desc"] or ""):  # a pasted spec table, not a description
        p["desc"] = f"{p['title']} {p['category']} flooring."
    if p["desc"] and p["desc"][-1] not in ".!?":
        p["desc"] += "."
    dump = spec_dump(p.get("raw_desc")) if p.get("raw_desc") else None
    if dump:  # the supplier pasted a spec list instead of a description
        typ, mat = dump.pop("Type Of Product", None), dump.pop("Pile Material", None)
        for k, v in clean_specs(dump).items():
            p["specs"].setdefault(k, v)
        noun = "carpet" if p["category"] == "carpet" else "flooring"
        p["desc"] = scrub_text(" ".join(x for x in [(typ or "").capitalize(), noun] if x.strip()) +
                               (f" in {mat}" if mat else "") + ".")
    if p.get("thickness") and UNCONFIRMED.search(str(p["thickness"])):
        p["thickness"] = None
    base = slugify(orig)
    slug, n = base, 2
    while slug in slugs:
        slug = f"{base}-{n}"
        n += 1
    slugs.add(slug)
    colours, used = [], set()
    for c in p.get("colours") or []:
        name = colour_name(c["name"], orig, p["title"])
        if len(name) <= 2:
            continue
        cs = slugify(name) or "colour"
        while cs in used:
            cs += "-x"
        used.add(cs)
        entry = {"name": name}
        if images and c.get("images"):
            fn = f"{slug}-{cs}.webp"
            if save_image(c["images"], IMG / fn, cache):
                entry["image"] = f"/img/products/{fn}"
        sp = clean_specs(c.get("specs"))
        if sp:
            entry["specs"] = sp
        colours.append(entry)
    if sum(1 for c in colours if c.get("image")) >= 2:  # never show a colour with the wrong (or no) photo
        colours = [c for c in colours if c.get("image")]
    fm = {"title": p["title"], "category": p["category"]}
    for k in ("subcategory", "thickness"):
        if p.get(k):
            fm[k] = p[k]
    if len(colours) > 1:
        fm["colours"] = colours
        withimg = [c["image"] for c in colours if c.get("image")]
        # lead with the sharpest photo so the grid card and first view look best
        sharp = next((i for i in withimg if width_of(ROOT / "src" / i.lstrip("/")) >= 640), None)
        if withimg:
            fm["image"] = sharp or withimg[0]
        if len(p["desc"]) < 60:
            p["desc"] = (p["desc"].rstrip(".") + ". " if p["desc"] else "") + f"Available in {len(colours)} colours."
    else:
        saved = []
        imgs = [c for c in (p.get("images") or [])] or [c["images"] for c in (p.get("colours") or []) if c.get("images")]
        if images:
            for i, urls in enumerate(imgs[:3]):
                fn = f"{slug}.webp" if i == 0 else f"{slug}-{i + 1}.webp"
                if save_image([urls] if isinstance(urls, str) or isinstance(urls[0], str) else urls, IMG / fn, cache):
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
    products = [p for p in products if p["category"] in SOLD and "wall covering" not in
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
