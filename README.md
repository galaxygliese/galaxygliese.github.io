# galaxygliese.github.io

A blog about AI and physics. Posts are written in LaTeX, built with pandoc + KaTeX,
and deployed to GitHub Pages. The background is a spacetime grid that bends around
your cursor like a gravity well. Full spec: `design/DESIGN.md`.

## Write a post

```
posts/2026-12-my-post/
├── index.tex      # \section, equation/align + \label/\eqref, figures, \cite, lstlisting
├── meta.yaml      # title, date, category (AI | Physics), tags, summary, math
├── refs.bib       # optional; enables citations + References section
└── figs/          # images, referenced as figs/plot.svg
```

```yaml
title: "My Post"
date: 2026-12-01
category: AI            # AI | Physics
tags: [VLM, GRPO]
summary: "One-line summary for cards, feeds, and link previews."
math: true              # load KaTeX on this page
# code: https://github.com/...   # optional "Code on GitHub" link
# image: figs/cover.png          # optional social preview image
# draft: true                    # skip this post
# toc: false                     # hide the table of contents
```

Shared macros (`\dd`, `\dv`, `\pdv`, `\tr`, `\slashed`) live in `macros.tex`.
Equations, figures, and sections are numbered across the whole post by `tools/crossref.lua`.

## Build locally

```bash
brew install pandoc node     # once
npm install                  # once: self-hosted KaTeX + equation checker
python3 build.py             # builds into public/
python3 -m http.server -d public 8000   # http://localhost:8000
```

## Deploy

Push to `main`. `.github/workflows/deploy.yml` runs `python build.py --strict`
(which fails on any pandoc warning or KaTeX error) and publishes `public/`.
One-time setup: **Settings → Pages → Source: GitHub Actions**.

Site name, links, and the home-page intro are in `site.yaml`; the About page is `pages/about.md`.
