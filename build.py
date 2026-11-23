#!/usr/bin/env python3
"""Build the static blog into public/.

    python3 build.py            # build (KaTeX check runs if node + katex are installed)
    python3 build.py --strict   # CI mode: KaTeX check is required, warnings are errors
    python3 -m http.server -d public 8000   # preview at http://localhost:8000

Requires pandoc >= 3.1 on PATH. Optional: `npm install` for self-hosted KaTeX
and the build-time equation check (without it, KaTeX loads from a CDN).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public"
POSTS = ROOT / "posts"
TEMPLATES = ROOT / "templates"
KATEX_DIST = ROOT / "node_modules" / "katex" / "dist"
KATEX_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.25/dist"
CATEGORIES = {"AI": "ai", "Physics": "physics"}

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"warning: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- tiny YAML
def parse_yaml(path: Path) -> dict:
    """Parse flat `key: value` YAML (strings, numbers, booleans, [a, b] lists)."""
    data: dict = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SystemExit(f"{path}:{n}: expected 'key: value'")
        key, val = line.split(":", 1)
        data[key.strip()] = _yaml_value(val.strip())
    return data


def _yaml_value(v: str):
    if v[:1] in "\"'":                          # quoted string, drop trailing comment
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    v = re.sub(r"\s+#.*$", "", v).strip()
    if v.startswith("[") and v.endswith("]"):
        return [_yaml_value(x.strip()) for x in v[1:-1].split(",") if x.strip()]
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    return v


# ---------------------------------------------------------------- helpers
def esc(s) -> str:
    return html.escape(str(s), quote=True)


def render(template: str, **ctx) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(ctx.get(m.group(1), "")), template)


def load_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def fmt_date(d: dt.date) -> str:
    return d.strftime("%b %-d, %Y") if sys.platform != "win32" else d.strftime("%b %d, %Y")


def to_date(v) -> dt.date:
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError:
        raise SystemExit(f"invalid date {v!r} (use YYYY-MM-DD)")


def run_pandoc(args: list[str], cwd: Path) -> str:
    try:
        p = subprocess.run(["pandoc", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("pandoc not found. Install it: https://pandoc.org/installing.html")
    for line in p.stderr.strip().splitlines():
        warn(f"{cwd.name}: {line}")
    if p.returncode != 0:
        raise SystemExit(f"pandoc failed in {cwd} (exit {p.returncode})")
    return p.stdout


def tag_html(category: str) -> str:
    slug = CATEGORIES.get(category, "other")
    return f'<a class="cat cat-{slug}" href="/{slug}/">{esc(category)}</a>'


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a PNG / JPEG / GIF / SVG, read from the header (no Pillow needed)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if data[:2] == b"\xff\xd8":                                  # JPEG: find the SOFn marker
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1; continue
            marker, seglen = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + seglen
        return None
    if path.suffix == ".svg":
        m = re.search(rb'viewBox="[\d.\s-]+?\s([\d.]+)\s+([\d.]+)"', data[:2000]) \
            or re.search(rb'<svg[^>]*?width="([\d.]+)[^"]*"[^>]*?height="([\d.]+)', data[:2000])
        return (float(m.group(1)), float(m.group(2))) if m else None
    return None


def equal_height_minipages(body: str, src: Path) -> str:
    """Side-by-side image minipages: flex-grow = aspect ratio, so every image in a row
    ends up the same height (like matching LaTeX subfigures)."""
    def aspect(div: str) -> float | None:
        img = re.search(r'<img [^>]*src="([^"]+)"', div)
        if "<table" in div or not img or img.group(1).startswith(("http:", "https:", "data:")):
            return None
        size = image_size(src / img.group(1))
        return size[0] / size[1] if size and size[1] else None

    def fix(fig: re.Match) -> str:
        html_ = fig.group(0)
        divs = re.findall(r'<div class="minipage">.*?</div>', html_, flags=re.S)
        ratios = [aspect(d) for d in divs]
        if len(divs) < 2 or None in ratios:        # only rows made purely of images
            return html_
        for d, r in zip(divs, ratios):
            html_ = html_.replace(d, d.replace('<div class="minipage">',
                                               f'<div class="minipage" style="flex-grow: {r:.4f}">', 1), 1)
        return html_
    return re.sub(r"<figure\b.*?</figure>", fix, body, flags=re.S)


_katex_flag = None
def katex_flag() -> str:
    """--katex is deprecated in newer pandoc (warns -> fails --strict); --math-method is unknown in old ones."""
    global _katex_flag
    if _katex_flag is None:
        out = subprocess.run(["pandoc", "--version"], capture_output=True, text=True).stdout
        ver = tuple(int(x) for x in re.search(r"pandoc\S* (\d+)\.(\d+)", out).groups())
        _katex_flag = "--math-method=katex" if ver >= (3, 10) else "--katex"
    return _katex_flag


# ---------------------------------------------------------------- page shell
class Site:
    def __init__(self, cfg: dict, katex_base: str):
        self.cfg = cfg
        self.base = load_template("base.html")
        # cache-busting: /static/css/style.css -> /static/css/style.css?v=<content hash>
        for asset in ("css/style.css", "js/gravity.js"):
            v = hashlib.sha1((ROOT / "static" / asset).read_bytes()).hexdigest()[:8]
            self.base = self.base.replace(f"/static/{asset}\"", f"/static/{asset}?v={v}\"")
        self.katex_base = katex_base
        self.url = cfg.get("url", "").rstrip("/")

    def footer_links(self) -> str:
        email = self.cfg.get("email")
        links = [("Email", email and f"mailto:{email}"),
                 ("GitHub", self.cfg.get("github")), ("LinkedIn", self.cfg.get("linkedin")),
                 ("Scholar", self.cfg.get("scholar")), ("RSS", "/feed.xml")]
        return "".join(f' · <a href="{esc(u)}">{n}</a>' for n, u in links if u)

    def page(self, path: str, title: str, content: str, *, description: str = "",
             nav: str = "", og_type: str = "website", og_image: str = "",
             math: bool = False, wide: bool = False) -> None:
        site_title = self.cfg.get("title", "")
        head, body_end = "", ""
        if math:
            head += f'<link rel="stylesheet" href="{self.katex_base}/katex.min.css">\n' \
                   f'<script src="{self.katex_base}/katex.min.js" defer></script>'
            body_end = ('<script>addEventListener("DOMContentLoaded",function(){'
                        'document.querySelectorAll(".math").forEach(function(e){'
                        'katex.render(e.textContent,e,{displayMode:e.classList.contains("display"),'
                        'throwOnError:false})})})</script>')
        out = render(
            self.base,
            page_title=esc(title if title == site_title else f"{title} · {site_title}"),
            title=esc(title), site_title=esc(site_title), author=esc(self.cfg.get("author", "")),
            description=esc(description or self.cfg.get("description", "")),
            canonical=esc(f"{self.url}{path}"), og_type=og_type,
            og_image=esc(og_image or f"{self.url}/static/img/og.png"),
            head_extra=head, body_end=body_end, content=content,
            main_class=' class="wide"' if wide else "",
            year=dt.date.today().year, footer_links=self.footer_links(),
            **{f"nav_{k}": (' aria-current="page"' if k == nav else "")
               for k in ("home", "ai", "physics", "about")},
        )
        dest = OUT / path.lstrip("/")
        if path.endswith("/"):
            dest = dest / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, encoding="utf-8")


# ---------------------------------------------------------------- posts
def build_post(site: Site, src: Path) -> dict | None:
    meta = parse_yaml(src / "meta.yaml")
    if meta.get("draft"):
        print(f"skip draft {src.name}")
        return None
    for key in ("title", "date", "category"):
        if key not in meta:
            raise SystemExit(f"{src}/meta.yaml: missing '{key}'")
    if meta["category"] not in CATEGORIES:
        raise SystemExit(f"{src}/meta.yaml: category must be one of {list(CATEGORIES)}")

    args = [str(ROOT / "macros.tex"), "index.tex", "--from", "latex", "--to", "html5",
            katex_flag(), "--lua-filter", str(ROOT / "tools" / "crossref.lua"),
            "--template", str(TEMPLATES / "post.html"),
            "--syntax-highlighting", "pygments",  # token classes only; colours live in style.css
            "--section-divs"]
    if meta.get("toc", True):
        args += ["--toc", "--toc-depth", "2"]
    if (src / "refs.bib").exists():
        args += ["--citeproc", "--bibliography", "refs.bib",
                 "--metadata", "reference-section-title=References", "--metadata", "link-citations=true"]
    body = run_pandoc(args, cwd=src)
    body = equal_height_minipages(body, src)
    body = re.sub(r"<img (?![^>]*loading=)", '<img loading="lazy" decoding="async" ', body)

    slug = src.name
    date = to_date(meta["date"])
    has_math = 'class="math' in body
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    minutes = max(1, round(words / 230))
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    code_url = meta.get("code") or f"{site.cfg.get('repo', '')}/tree/main/posts/{slug}"
    code_label = "Code on GitHub" if meta.get("code") else "Source on GitHub"
    header = (
        '<header class="post-header">'
        f'<div class="meta">{tag_html(meta["category"])}'
        f'<time datetime="{date.isoformat()}">{fmt_date(date)}</time>'
        f'<span>{minutes} min read</span></div>'
        f'<h1>{esc(meta["title"])}</h1>'
        + (f'<p class="summary">{esc(meta["summary"])}</p>' if meta.get("summary") else "")
        + (f'<ul class="tags">{"".join(f"<li>#{esc(t)}</li>" for t in tags)}</ul>' if tags else "")
        + "</header>"
    )
    footer = f'<footer class="post-footer"><a href="{esc(code_url)}">{code_label} →</a></footer>'
    content = f'<article class="panel post">{header}{body}{footer}</article>'

    image = meta.get("image")
    og_image = f"{site.url}/posts/{slug}/{image}" if image else ""
    site.page(f"/posts/{slug}/", meta["title"], content, description=meta.get("summary", ""),
              nav=CATEGORIES[meta["category"]], og_type="article", og_image=og_image,
              math=bool(meta.get("math", has_math)), wide=True)

    # copy assets (figures, data, ...) that the page links to; skip sources and unused files
    for f in src.rglob("*"):
        rel = f.relative_to(src).as_posix()
        if f.is_file() and f.suffix not in {".tex", ".bib", ".yaml", ".aux", ".log"} \
                and (f'"{rel}"' in content or rel == image):
            dest = OUT / "posts" / slug / f.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)

    return {"slug": slug, "title": meta["title"], "date": date, "category": meta["category"],
            "summary": meta.get("summary", ""), "tags": tags, "minutes": minutes}


def card(p: dict) -> str:
    return (
        '<article class="card">'
        f'<div class="meta">{tag_html(p["category"])}'
        f'<time datetime="{p["date"].isoformat()}">{fmt_date(p["date"])}</time>'
        f'<span>{p["minutes"]} min read</span></div>'
        f'<h2><a href="/posts/{p["slug"]}/">{esc(p["title"])}</a></h2>'
        + (f'<p>{esc(p["summary"])}</p>' if p["summary"] else "")
        + "</article>"
    )


def build_lists(site: Site, posts: list[dict]) -> None:
    tpl = load_template("list.html")
    empty = '<p class="empty panel">No posts yet. The spacetime is still flat.</p>'
    cards = "\n".join(card(p) for p in posts[:10]) or empty
    site.page("/", site.cfg.get("title", ""),
              render(tpl, heading=esc(site.cfg.get("title", "")), intro=site.cfg.get("intro", ""), cards=cards),
              nav="home")
    blurbs = {"AI": "Machine learning, vision-language models, reinforcement learning and everything in between.",
              "Physics": "Relativity, quantum field theory, statistical mechanics, and the math that ties them together."}
    for cat, slug in CATEGORIES.items():
        sel = [p for p in posts if p["category"] == cat]
        site.page(f"/{slug}/", cat,
                  render(tpl, heading=cat, intro=blurbs[cat], cards="\n".join(map(card, sel)) or empty),
                  nav=slug, description=blurbs[cat])


def build_about(site: Site) -> None:
    src = ROOT / "pages" / "about.md"
    body = run_pandoc([str(src), "--from", "markdown", "--to", "html5"], cwd=src.parent)
    email = site.cfg.get("email")
    links = [("Email", email and f"mailto:{email}"),
             ("GitHub", site.cfg.get("github")), ("LinkedIn", site.cfg.get("linkedin")),
             ("Google Scholar", site.cfg.get("scholar")), ("CV (PDF)", site.cfg.get("cv"))]
    pills = "".join(f'<a class="pill" href="{esc(u)}">{n}</a>' for n, u in links if u)
    content = (f'<article class="panel post about"><h1>About</h1><div class="post-body">{body}</div>'
               f'<p class="pills">{pills}</p></article>')
    site.page("/about/", "About", content, nav="about", wide=True)


def build_feed(site: Site, posts: list[dict]) -> None:
    def ts(d: dt.date) -> str:
        return f"{d.isoformat()}T00:00:00Z"
    updated = ts(posts[0]["date"]) if posts else ts(dt.date.today())
    entries = "".join(
        f"""
  <entry>
    <title>{esc(p["title"])}</title>
    <link href="{site.url}/posts/{p["slug"]}/"/>
    <id>{site.url}/posts/{p["slug"]}/</id>
    <updated>{ts(p["date"])}</updated>
    <category term="{esc(p["category"])}"/>
    <summary>{esc(p["summary"])}</summary>
  </entry>""" for p in posts)
    feed = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{esc(site.cfg.get("title", ""))}</title>
  <subtitle>{esc(site.cfg.get("description", ""))}</subtitle>
  <link href="{site.url}/feed.xml" rel="self"/>
  <link href="{site.url}/"/>
  <id>{site.url}/</id>
  <updated>{updated}</updated>
  <author><name>{esc(site.cfg.get("author", ""))}</name></author>{entries}
</feed>
"""
    (OUT / "feed.xml").write_text(feed, encoding="utf-8")


def setup_katex(strict: bool) -> str:
    if (KATEX_DIST / "katex.min.js").exists():
        dest = OUT / "static" / "katex"
        (dest / "fonts").mkdir(parents=True, exist_ok=True)
        for name in ("katex.min.css", "katex.min.js"):
            shutil.copy2(KATEX_DIST / name, dest / name)
        for font in (KATEX_DIST / "fonts").glob("*.woff2"):
            shutil.copy2(font, dest / "fonts" / font.name)
        return "/static/katex"
    if strict:
        raise SystemExit("KaTeX not installed: run `npm install` first")
    warn("node_modules/katex missing; pages will load KaTeX from a CDN (run `npm install`)")
    return KATEX_CDN


def check_math(strict: bool) -> None:
    node = shutil.which("node")
    if not node or not KATEX_DIST.exists():
        if strict:
            raise SystemExit("node + katex are required for the equation check")
        warn("skipping KaTeX equation check (needs node and `npm install`)")
        return
    if subprocess.run([node, str(ROOT / "tools" / "check-math.mjs"), str(OUT)]).returncode != 0:
        raise SystemExit("KaTeX errors found, build failed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="CI mode: fail on warnings, require KaTeX check")
    a = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT / "static")
    (OUT / ".nojekyll").touch()

    site = Site(parse_yaml(ROOT / "site.yaml"), setup_katex(a.strict))
    posts = [p for d in sorted(POSTS.iterdir()) if (d / "index.tex").exists()
             for p in [build_post(site, d)] if p]
    posts.sort(key=lambda p: p["date"], reverse=True)

    build_lists(site, posts)
    build_about(site)
    build_feed(site, posts)
    site.page("/404.html", "Lost in spacetime",
              '<article class="panel post center"><h1>404</h1><p>This page fell past the event horizon.</p>'
              '<p><a href="/">← Back to home</a></p></article>')
    check_math(a.strict)

    print(f"Built {len(posts)} post(s) into {OUT.relative_to(ROOT)}/")
    if a.strict and WARNINGS:
        raise SystemExit(f"{len(WARNINGS)} warning(s) in strict mode")


if __name__ == "__main__":
    main()
