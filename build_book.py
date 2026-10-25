"""Build book.html: EXPLAINER.md as a two-pane reading page.

Left pane  : table of contents (chapters, then their sections), sticky, with a
             filter box and scroll-spy highlighting.
Right pane : the book itself, rendered from EXPLAINER.md.

The look borrows the palette and type from `anthropic-ui.css` in this repo
(warm paper, terracotta accent, serif headings, mono code) but is self-contained:
one HTML file, no external CSS, no JS build step, works from file://.

    uv run python build_book.py          # writes book.html

Requires `markdown` (see the dev dependency group in pyproject.toml).
"""

import html
import pathlib
import re

import markdown

ROOT = pathlib.Path(__file__).parent
SOURCE = ROOT / "EXPLAINER.md"
TARGET = ROOT / "book.html"

# --------------------------------------------------------------------------
# CSS - palette and type inspired by anthropic-ui.css
# --------------------------------------------------------------------------

CSS = """
:root {
  --paper: #f0eee6;
  --surface: #fbfaf7;
  --ivory: #fffdfa;
  --ink: #1f1e1d;
  --muted: #55524c;
  --stone: #8c877c;
  --line: #e2ddd2;
  --line-soft: #ece8df;
  --terra: #d97757;
  --terra-dark: #c9633f;
  --code-bg: #23211e;
  --code-fg: #f3eee5;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --sans: -apple-system, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  --mono: "JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace;
  --sidebar: 400px;          /* 1.25x the original 320px */
  --measure: 80%;            /* reading column fills 80% of the pane */
}

* { box-sizing: border-box; }

html, body { height: 100%; }

body {
  margin: 0;
  display: grid;
  grid-template-columns: var(--sidebar) minmax(0, 1fr);
  height: 100vh;
  background: var(--paper);
  color: var(--ink);
  font: 17px/1.62 var(--sans);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* ---------- left pane ---------- */

#sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--surface);
}

.brand {
  padding: 27px 27px 20px;
  border-bottom: 1px solid var(--line-soft);
}

.brand .eyebrow {
  margin: 0 0 6px;
  color: #a14e2f;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.brand h1 {
  margin: 0;
  font: 500 27.5px/1.2 var(--serif);
  letter-spacing: -.01em;
}

.brand p {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: 15.5px;
}

.filter {
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--line-soft);
}

.filter input {
  width: 100%;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--ivory);
  color: var(--ink);
  font: 16px var(--sans);
}

.filter input:focus-visible {
  outline: 2px solid #e3a98f;
  outline-offset: 1px;
}

#toc {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 10px 48px;
  scrollbar-width: thin;
}

#toc ol, #toc ul { margin: 0; padding: 0; list-style: none; }

#toc .chapter > a {
  display: block;
  padding: 10px 12px 5px;
  color: var(--ink);
  font: 600 17px/1.35 var(--sans);
  text-decoration: none;
  border-radius: 7px;
}

#toc .chapter > a:hover { background: #f4f1e9; }

#toc .chapter > a .num {
  display: inline-block;
  min-width: 27px;
  color: var(--terra-dark);
  font-variant-numeric: tabular-nums;
}

#toc .sections { margin: 0 0 6px; padding: 0 0 0 6px; list-style: none; }

#toc .frontmatter > a {
  color: var(--muted);
  font: 500 15.5px/1.35 var(--sans);
  letter-spacing: .01em;
}

#toc .sections a {
  display: block;
  padding: 4px 12px 4px 30px;
  color: var(--muted);
  font-size: 15.5px;
  line-height: 1.35;
  text-decoration: none;
  border-left: 2px solid transparent;
}

#toc .sections a:hover { color: var(--ink); background: #f4f1e9; }

#toc a.active {
  color: var(--ink);
  background: #f6ede6;
  border-left-color: var(--terra);
}

#toc .sections a.active { color: #8f3f27; font-weight: 600; }

#toc .hidden { display: none; }

.sidebar-foot {
  padding: 12px 20px 18px;
  border-top: 1px solid var(--line-soft);
  color: var(--stone);
  font-size: 14.5px;
}

.sidebar-foot a { color: var(--terra-dark); text-decoration: none; }

/* ---------- right pane ---------- */

#pane {
  position: relative;
  min-width: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

#progress {
  position: sticky;
  top: 0;
  z-index: 5;
  height: 3px;
  background: transparent;
}

#progress > span {
  display: block;
  width: 0;
  height: 100%;
  background: var(--terra);
  transition: width .12s linear;
}

#content {
  max-width: var(--measure);
  margin: 0 auto;
  padding: 68px 54px 170px;
  font-size: 34px;         /* 2x the 17px base */
  line-height: 1.62;
}

#content > h1:first-child { display: none; }  /* the title lives in the sidebar */

#content a[id] { display: block; scroll-margin-top: 24px; }

h2, h3 { scroll-margin-top: 24px; }

h1, h2, h3, h4 {
  color: var(--ink);
  text-wrap: balance;
}

h2 {
  margin: 4.5rem 0 1rem;
  padding-top: 1.6rem;
  border-top: 1px solid var(--line);
  font: 500 60px/1.14 var(--serif);
  letter-spacing: -.015em;
  scroll-margin-top: 24px;
}

#content > h2:first-of-type { border-top: 0; margin-top: 0; padding-top: 0; }

h3 {
  margin: 2.4rem 0 .7rem;
  font: 600 38px/1.25 var(--sans);
  letter-spacing: -.01em;
  scroll-margin-top: 24px;
}

h4 { margin: 1.8rem 0 .5rem; font: 600 30px/1.3 var(--sans); }

p { margin: 0 0 1.05rem; }

a { color: var(--terra-dark); text-underline-offset: 2px; }

strong { font-weight: 650; }

hr {
  height: 1px;
  margin: 3rem 0;
  border: 0;
  background: var(--line);
}

ul, ol { margin: 0 0 1.1rem; padding-left: 1.4rem; }

li { margin: .3rem 0; }

li > p { margin: .3rem 0; }

/* the "You are here" block quotes */
blockquote {
  margin: 1.4rem 0;
  padding: 14px 18px;
  border: 1px solid #e7cec2;
  border-left: 5px solid var(--terra);
  border-radius: 12px;
  background: #f8eee8;
  color: #3d3d3a;
}

blockquote p { margin: 0; }
blockquote p + p { margin-top: .5rem; }

/* tables */
table {
  width: 100%;
  margin: 1.3rem 0 1.6rem;
  border-collapse: collapse;
  font-size: 28px;
}

th {
  padding: 8px 10px;
  border-bottom: 2px solid var(--line);
  color: var(--muted);
  font-weight: 650;
  text-align: left;
  vertical-align: bottom;
}

td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line-soft);
  vertical-align: top;
}

tr:hover td { background: #f7f4ee; }

/* code */
code {
  padding: 1px 5px;
  border-radius: 5px;
  background: #eae7de;
  color: #6f3b26;
  font: .875em/1.4 var(--mono);
}

pre {
  position: relative;
  margin: 1.2rem 0 1.5rem;
  padding: 16px 18px;
  border-radius: 12px;
  background: var(--code-bg);
  color: var(--code-fg);
  overflow-x: auto;
  font: 20px/1.55 var(--mono);   /* just under 2x so ASCII diagrams fit */
  white-space: pre;                 /* ASCII diagrams must not be re-flowed */
  tab-size: 4;
}

pre code {
  padding: 0;
  background: none;
  color: inherit;
  font: inherit;
}

pre::-webkit-scrollbar { height: 10px; }
pre::-webkit-scrollbar-thumb { background: #4a463f; border-radius: 999px; }

.copy {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 3px 9px;
  border: 1px solid #4a463f;
  border-radius: 6px;
  background: #2c2a26;
  color: #d8d2c6;
  font: 11px var(--sans);
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s, background .15s;
}

pre:hover .copy, .copy:focus-visible { opacity: 1; }
.copy:hover { background: #3a3732; }

/* collapsible checkpoint answers */
details {
  margin: .8rem 0;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--ivory);
}

details[open] { border-color: #e7cec2; background: #fdf9f5; }

summary {
  color: var(--terra-dark);
  font-weight: 600;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker { display: none; }

summary::before {
  display: inline-block;
  width: 1em;
  color: var(--terra);
  content: "▸";
  transition: transform .15s;
}

details[open] summary::before { transform: rotate(90deg); }

details p { margin: .7rem 0 0; color: var(--muted); font-size: 30px; }

details code { font-size: .85em; }

/* chapter navigation appended by this script */
.chnav {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 3rem 0 0;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  font-size: 27px;
}

.chnav a {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--ivory);
  text-decoration: none;
}

.chnav a:hover { border-color: #e7cec2; background: #fdf9f5; }

.chnav .grow { flex: 1; }

/* mobile: the sidebar becomes a drawer */
#menu {
  display: none;
  position: fixed;
  z-index: 20;
  top: 12px;
  left: 12px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  color: var(--ink);
  font: 13px var(--sans);
  cursor: pointer;
}

@media (max-width: 980px) {
  body { grid-template-columns: 1fr; }

  #sidebar {
    position: fixed;
    z-index: 15;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(86vw, 425px);
    transform: translateX(-102%);
    transition: transform .2s ease;
    box-shadow: 0 0 40px rgba(31, 30, 29, .18);
  }

  body.nav-open #sidebar { transform: translateX(0); }

  #menu { display: block; }

  #sidebar .brand { padding-top: 58px; }   /* clear the floating button */

  #content { padding: 72px 24px 110px; font-size: 26px; }
}

@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1b1a18;
    --surface: #201f1c;
    --ivory: #262420;
    --ink: #f2ece1;
    --muted: #c3bcae;
    --stone: #9a9384;
    --line: #34312b;
    --line-soft: #2b2823;
    --code-bg: #141312;
    --code-fg: #f3eee5;
  }

  body { background: var(--paper); }
  code { background: #322e28; color: #f0b49a; }
  blockquote { background: #2a211d; border-color: #4a332b; color: #e6ded2; }
  details[open] { background: #262420; }
  tr:hover td { background: #262420; }
  #toc .chapter > a:hover, #toc .sections a:hover { background: #262420; }
  #toc a.active { background: #33261f; }
  #toc .sections a.active { color: #f0b49a; }
  .chnav a:hover { background: #262420; }
}

@media print {
  body { display: block; height: auto; }
  #sidebar, #menu, #progress, .copy, .chnav { display: none !important; }
  #pane { overflow: visible; }
  /* the on-screen column is 2x; print gets back to a sane page scale */
  #content { max-width: none; padding: 0; font-size: 11pt; line-height: 1.5; }
  h2 { font-size: 20pt; margin: 1.4em 0 .5em; }
  h3 { font-size: 13pt; }
  h4 { font-size: 11pt; }
  table { font-size: 9pt; }
  details p { font-size: 10pt; }
  pre { white-space: pre-wrap; page-break-inside: avoid; font-size: 7.5pt; }
  a { color: inherit; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  * { transition-duration: .01ms !important; }
}
"""

JS = """
(() => {
  const pane = document.getElementById('pane');
  const toc = document.getElementById('toc');
  const links = [...toc.querySelectorAll('a[href^="#"]')];
  const bar = document.querySelector('#progress > span');
  const body = document.body;

  // ---- scroll-spy: the last heading whose top has passed the reading line ----
  // (a scroll handler beats IntersectionObserver here: headings are tall and
  // several can be visible at once, which made the observer pick the wrong one)
  const targets = links
    .map(a => ({ id: a.getAttribute('href').slice(1), el: document.getElementById(a.getAttribute('href').slice(1)) }))
    .filter(t => t.el);

  const setActive = (id) => {
    links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
    // keep the highlighted entry visible in the (independently scrolling) sidebar
    const active = links.find(a => a.getAttribute('href') === '#' + id);
    if (active) {
      const box = active.getBoundingClientRect();
      const paneBox = toc.getBoundingClientRect();
      if (box.top < paneBox.top || box.bottom > paneBox.bottom) {
        active.scrollIntoView({ block: 'nearest' });
      }
    }
  };

  const sync = () => {
    const max = pane.scrollHeight - pane.clientHeight;
    if (bar) bar.style.width = (max > 0 ? (pane.scrollTop / max) * 100 : 0).toFixed(2) + '%';

    const line = 96;                       // px below the top of the pane
    let current = targets.length ? targets[0].id : null;
    for (const t of targets) {
      if (t.el.getBoundingClientRect().top - pane.getBoundingClientRect().top <= line) current = t.id;
    }
    if (current) setActive(current);
  };

  pane.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync);
  sync();

  // ---- TOC filter ----
  const filter = document.getElementById('filter');
  if (filter) {
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      toc.querySelectorAll('.chapter').forEach(ch => {
        let any = false;
        const head = ch.querySelector(':scope > a');
        const headHit = head.textContent.toLowerCase().includes(q);
        ch.querySelectorAll('.sections a').forEach(a => {
          const hit = !q || a.textContent.toLowerCase().includes(q) || headHit;
          a.parentElement.classList.toggle('hidden', !hit);
          any = any || hit;
        });
        if (!q) ch.querySelectorAll('.sections li').forEach(li => li.classList.remove('hidden'));
        ch.classList.toggle('hidden', q && !any && !headHit);
      });
    });
  }

  // ---- copy buttons on code blocks ----
  document.querySelectorAll('#content pre').forEach(pre => {
    const btn = document.createElement('button');
    btn.className = 'copy';
    btn.type = 'button';
    btn.textContent = 'Copy';
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pre.innerText.replace(/^Copy\\n?/, ''));
        btn.textContent = 'Copied';
      } catch {
        btn.textContent = 'Ctrl+C';
      }
      setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
    });
    pre.appendChild(btn);
  });

  // ---- mobile drawer ----
  const menu = document.getElementById('menu');
  if (menu) {
    menu.addEventListener('click', () => body.classList.toggle('nav-open'));
    toc.addEventListener('click', (e) => {
      if (e.target.closest('a')) body.classList.remove('nav-open');
    });
    pane.addEventListener('click', () => body.classList.remove('nav-open'));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') body.classList.remove('nav-open');
    });
  }

  // ---- open the first collapsed answer when printing ----
  window.addEventListener('beforeprint', () => {
    document.querySelectorAll('details').forEach(d => d.open = true);
  });
})();
"""


def render(md_text: str) -> str:
    """Markdown -> HTML, keeping raw HTML (details/a id) and adding heading ids."""
    return markdown.markdown(
        md_text,
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
    )


def build_toc(body_html: str) -> str:
    """Sidebar nav: one entry per chapter (h2) with its h3 sections underneath."""
    headings = re.findall(
        r'<h([23])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>', body_html, re.S
    )

    def plain(fragment: str) -> str:
        text = re.sub(r"<[^>]+>", "", fragment)
        return html.unescape(text).strip()

    chapters = []          # [(anchor_id, title, [(id, title), ...])]
    for level, hid, inner in headings:
        title = plain(inner)
        if level == "2" and title == "Contents":
            continue  # the book's own contents table; the sidebar already is one
        if level == "2":
            match = re.match(r"Chapter\s+(\d+)", title)
            anchor = f"ch{int(match.group(1)):02d}" if match else hid
            chapters.append((anchor, title, []))
        elif chapters:
            chapters[-1][2].append((hid, title))

    out = ["<ol>"]
    for anchor, title, sections in chapters:
        match = re.match(r"Chapter\s+(\d+)\s*[—-]\s*(.*)", title)
        if match:
            label = f'<span class="num">{int(match.group(1)):02d}</span>{html.escape(match.group(2))}'
        else:
            label = html.escape(title)
        kind = "chapter" if match else "chapter frontmatter"
        out.append(f'<li class="{kind}"><a href="#{anchor}">{label}</a>')
        if sections:
            out.append('<ul class="sections">')
            for hid, stitle in sections:
                out.append(f'<li><a href="#{hid}">{html.escape(stitle)}</a></li>')
            out.append("</ul>")
        out.append("</li>")
    out.append("</ol>")
    return "\n".join(out)


def add_chapter_nav(body_html: str, chapters) -> str:
    """Append 'previous / next' links at the end of each chapter.

    python-markdown wraps the raw `<a id="chNN">` anchors in a paragraph, and
    inserting inside that paragraph produces `<p><div>` (invalid nesting). So:
    unwrap the anchors, then split the document on them and rebuild it, adding
    the strip to the end of each segment.
    """
    def nav(prev, nxt):
        left = (f'<a class="grow" href="#{prev[0]}">← {html.escape(prev[1])}</a>'
                if prev else '<span class="grow"></span>')
        right = (f'<a class="grow" href="#{nxt[0]}">{html.escape(nxt[1])} →</a>'
                 if nxt else '<span class="grow"></span>')
        return f'<div class="chnav">{left}{right}</div>'

    # 1. unwrap `<p><a id="chNN"></a></p>` into a bare anchor
    body = re.sub(r'<p>\s*(<a id="ch\d\d"></a>)\s*</p>', r"\1", body_html)

    # 2. split on the anchors, keeping them
    pattern = r'(<a id="ch\d\d"></a>)'
    parts = re.split(pattern, body)
    # parts: [front matter, anchor1, body1, anchor2, body2, ...]

    out = [parts[0]]
    for index, anchor in enumerate(chapters):
        anchor_html = parts[1 + index * 2]
        segment = parts[2 + index * 2] if 2 + index * 2 < len(parts) else ""
        prev = chapters[index - 1] if index > 0 else None
        nxt = chapters[index + 1] if index + 1 < len(chapters) else None

        if nxt is None:
            # last chapter: keep the appendices after the strip
            split_at = segment.find('<h2 id="appendix-a')
            if split_at == -1:
                segment = segment + nav(prev, None)
            else:
                segment = segment[:split_at] + nav(prev, None) + "\n" + segment[split_at:]
        else:
            segment = segment + nav(prev, nxt)

        out.extend([anchor_html, segment])

    return "".join(out)


def main():
    md_text = SOURCE.read_text(encoding="utf-8")
    body = render(md_text)

    toc = build_toc(body)

    chapters = []
    for level, hid, inner in re.findall(r'<h([23])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>', body, re.S):
        if level == "2":
            title = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
            match = re.match(r"Chapter\s+(\d+)", title)
            if match:                       # front matter and appendices get no nav
                chapters.append((f"ch{int(match.group(1)):02d}", title))
    body = add_chapter_nav(body, chapters)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nanocode, explained</title>
<meta name="description" content="A chapter-by-chapter walkthrough of a small coding agent, written for students.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<button id="menu" type="button" aria-label="Toggle contents">☰ Contents</button>

<nav id="sidebar" aria-label="Table of contents">
  <div class="brand">
    <p class="eyebrow">Build your own coding agent</p>
    <h1>Nanocode, explained</h1>
    <p>A chapter-by-chapter walkthrough for students.</p>
  </div>
  <div class="filter">
    <input id="filter" type="search" placeholder="Filter chapters and sections…" aria-label="Filter table of contents">
  </div>
  <div id="toc">{toc}</div>
  <div class="sidebar-foot">
    Rendered from <code>EXPLAINER.md</code> by <code>build_book.py</code>.
  </div>
</nav>

<main id="pane">
  <div id="progress" aria-hidden="true"><span></span></div>
  <article id="content">
{body}
  </article>
</main>

<script>{JS}</script>
</body>
</html>
"""

    TARGET.write_text(page, encoding="utf-8")
    print(f"book.html written: {len(page):,} chars, {page.count('<h2')} chapters, {page.count('<h3')} sections")


if __name__ == "__main__":
    main()
