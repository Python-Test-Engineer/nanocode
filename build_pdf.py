"""Build a book PDF: print an HTML page with headless Chrome, then add bookmarks.

    uv run python build_pdf.py                        # chNN/*.md -> EXPLAINER.md -> book.html -> book.pdf
    uv run python build_pdf.py page.html out.pdf      # print any HTML -> out.pdf
    uv run python build_pdf.py page.html --title "…"  # override the PDF metadata title

The default run has three steps, each reusable on its own:

    1. build_explainer.py   concatenates chNN/EXPLAINER_chNN.md, adds front matter,
                            TOC and appendices, demotes chapter headings one level.
    2. build_book.py        renders that Markdown to the two-pane book.html.
    3. this script          prints book.html to A4 PDF with Chrome's own print
                            engine and then adds what the print engine will not:
                            a real PDF outline (chapter and section bookmarks that
                            the reader shows in its sidebar) and page numbers in
                            the Contents table.

Given an HTML file, steps 1 and 2 are skipped: any page that carries its own
print stylesheet (an `@page` rule, and h1/h2/h3 at 30/19/12.5pt so the scanner
below can tell them apart) prints the same way. `explainer-harness-js.html` is
one such page; `book.html` is another.

Two print passes: the first has no page numbers, its page map is read back out of
the finished PDF, and the second prints the Contents table with those numbers. If
filling them in shifted pagination at all, a third pass converges. Folios come
from CSS `@bottom-center { content: counter(page) }` in build_book.py, so a folio
and a Contents entry always agree.

No LaTeX, no pandoc: Chrome renders, PyMuPDF only writes bookmarks and metadata
onto the finished file. Set CHROME_PATH to override the browser that gets used.
"""

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pymupdf

ROOT = pathlib.Path(__file__).parent
HTML = ROOT / "book.html"
PDF = ROOT / "book.pdf"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

# The print stylesheet's heading sizes in pt. Everything else in the PDF is body
# text, code, tables or folios and must not become a bookmark.
TITLE_MIN = 23.0
H2_RANGE = (17.0, 21.0)
H3_RANGE = (11.5, 13.5)

CNUM = re.compile(r"^Chapter\s+(\d+)\b")
ROW = re.compile(
    r'(<tr>\s*<td><a href="#ch(\d+)">(\d+)</a></td>\s*<td>.*?</td>\s*<td>.*?</td>\s*)(</tr>)',
    re.S,
)
TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Print an HTML book page to PDF and add a PDF outline."
    )
    parser.add_argument(
        "html",
        nargs="?",
        help="HTML to print; omit it to rebuild book.html from the Markdown first",
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        help="output PDF (default: book.pdf, or the HTML's own name with .pdf)",
    )
    parser.add_argument("--title", help="PDF metadata title (default: the page's <title>)")
    parser.add_argument(
        "--subject", default="A chapter-by-chapter walkthrough of a small coding agent"
    )
    parser.add_argument(
        "--contents",
        action="store_true",
        help="fill page numbers into the Contents table (always on when no HTML is given)",
    )
    return parser.parse_args(argv)


def find_browser():
    override = os.environ.get("CHROME_PATH")
    if override:
        return override
    for candidate in BROWSERS:
        if pathlib.Path(candidate).exists():
            return candidate
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("no Chrome/Edge found; set CHROME_PATH to a browser executable")


def run(step, *args):
    print(f"[{step}] {' '.join(str(a) for a in args)}", flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


DETAILS_OPEN = re.compile(r"<details(?![^>]*\bopen\b)")
PG_STYLE = "<style>th.pg,td.pg{text-align:right;white-space:nowrap}</style>"


def printable(html: str, pages: dict[int, int] | None = None) -> str:
    """Prepare the throwaway copy that gets printed.

    Two screen-only conveniences have to be undone for paper:

    * every `<details>` must be opened, or a checkpoint prints as a bare question
      (a closed details is display:none). `beforeprint` would do this, but headless
      print-to-pdf never dispatches that event.
    * the Contents table gains a Page column (`pages`), because a printed table of
      contents without page numbers is a table of links into nothing.
    """
    out = DETAILS_OPEN.sub("<details open", html)

    if pages:
        def row(match):
            body, _href, number, tail = match.groups()
            page = pages.get(int(number))
            cell = f'<td class="pg">{page}</td>' if page else "<td></td>"
            return body + cell + tail

        out, count = ROW.subn(row, out)
        if count:
            out = out.replace(
                "<th>The one new idea</th>",
                '<th>The one new idea</th><th class="pg">Page</th>',
                1,
            )
            out = out.replace("</head>", f"{PG_STYLE}</head>", 1)
            print(f"       contents table: {count} page numbers filled in", flush=True)
    return out


def print_pdf(browser, markup: str, out: pathlib.Path) -> pathlib.Path:
    """Write `markup` to a temp file and print it to `out` with Chrome."""
    tmpdir = tempfile.mkdtemp(prefix="bookpdf-")
    source = pathlib.Path(tmpdir) / "book.html"
    source.write_text(markup, encoding="utf-8")
    try:
        result = subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=10000",
                f"--print-to-pdf={out.resolve().as_posix()}",
                source.as_uri(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if result.returncode != 0 or not out.exists():
        sys.exit(f"printing failed:\n{result.stderr[-2000:]}")
    return out


def scan(pdf_path: pathlib.Path) -> list[tuple[int, str, int]]:
    """Read the printed headings back out of the PDF, by font size.

    Returns (level, text, page) with 1-based pages: level 0 is the book title,
    1 a chapter or appendix, 2 a section. Font size beats text matching here:
    chapter titles wrap across lines, and the Contents table repeats every
    chapter name in a smaller font on an earlier page.
    """
    found = []
    doc = pymupdf.open(pdf_path)
    for pno, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            lines = [line for line in block["lines"] if line["spans"]]
            if not lines:
                continue
            size = round(max(s["size"] for line in lines for s in line["spans"]), 1)
            # Keep only the lines drawn at the block's own size: the title block
            # also holds the small letter-spaced eyebrow above it, and a chapter
            # heading holds its small chapter number inline. Both would otherwise
            # end up inside the bookmark's text. A wrapped heading keeps every
            # line, so its title still reads whole.
            lines = [
                line
                for line in lines
                if round(max(s["size"] for s in line["spans"]), 1) == size
            ]
            if not lines:
                continue
            text = " ".join(
                " ".join(s["text"] for s in line["spans"]).strip() for line in lines
            )
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            if size >= TITLE_MIN:
                found.append((0, text, pno))
            elif H2_RANGE[0] <= size <= H2_RANGE[1]:
                found.append((1, text, pno))
            elif H3_RANGE[0] <= size <= H3_RANGE[1]:
                found.append((2, text, pno))
    doc.close()
    return found


def chapter_pages(headings) -> dict[int, int]:
    """{chapter number: page} from the scanned headings."""
    pages = {}
    for _level, text, pno in headings:
        match = CNUM.match(text)
        if match:
            pages.setdefault(int(match.group(1)), pno)
    return pages


def add_outline(pdf_path: pathlib.Path, headings, title: str, subject: str) -> int:
    """Write the PDF outline: the bookmark tree a reader shows in its sidebar."""
    doc = pymupdf.open(pdf_path)
    toc, seen = [], set()
    for level, text, pno in headings:
        entry = [1 if level == 0 else level, text, pno]
        if (entry[0], entry[1]) in seen:
            continue
        seen.add((entry[0], entry[1]))
        if entry[0] > 1 and not toc:      # a section with nothing above it
            entry[0] = 1
        toc.append(entry)
    doc.set_toc(toc)
    doc.set_metadata(
        {
            "title": title,
            "subject": subject,
            "keywords": "agent, LLM, tools, education",
            "creator": "build_pdf.py",
        }
    )
    doc.saveIncr()
    doc.close()
    return len(toc)


def page_title(markup: str, fallback: str) -> str:
    """A page's <title> is a good enough default for the PDF's metadata."""
    match = TITLE.search(markup)
    if not match:
        return fallback
    text = re.sub(r"<[^>]+>", "", match.group(1))
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("&middot;", "·").replace("&mdash;", "—").replace("&amp;", "&")
    return text or fallback


def main(argv=None):
    args = parse_args(argv)
    py = sys.executable

    if args.html:
        html_path = pathlib.Path(args.html)
        if not html_path.exists():
            sys.exit(f"{html_path} does not exist")
        pdf_path = pathlib.Path(args.pdf) if args.pdf else html_path.with_suffix(".pdf")
        # Nothing to rebuild: the page is its own source. Its Contents table, if
        # it has one, still takes page numbers -- that is what --contents asks
        # for, and what the default run always does for book.html.
        contents = args.contents
    else:
        run("1/3", py, "build_explainer.py")
        run("2/3", py, "build_book.py")
        html_path = HTML
        pdf_path = pathlib.Path(args.pdf) if args.pdf else PDF
        contents = True
    if not html_path.exists():
        sys.exit(f"{html_path.name} was not produced")

    markup = html_path.read_text(encoding="utf-8")
    title = args.title or page_title(markup, html_path.stem)
    browser = find_browser()
    print(
        f"[3/3] printing {html_path.name} -> {pdf_path.name} with "
        f"{pathlib.Path(browser).name}",
        flush=True,
    )

    pages: dict[int, int] = {}
    # Which chapters the page promises, taken from its own Contents links rather
    # than from a fixed list: the same check then works for a book of any length.
    expected = {int(n) for n in re.findall(r'href="#ch(\d+)"', markup)}
    for attempt in (1, 2, 3):
        print_pdf(browser, printable(markup, pages), pdf_path)
        if not contents:
            break
        found = chapter_pages(scan(pdf_path))
        missing = sorted(expected - set(found))
        if missing:
            print(f"       warning: no page found for chapters {missing}", flush=True)
        if found == pages:
            break
        if pages:
            print("       page numbers moved the layout; printing again", flush=True)
        else:
            print("       first pass read back; filling page numbers in", flush=True)
        pages = found
    else:
        print("       warning: page numbers never settled; Contents may be off", flush=True)

    entries = add_outline(pdf_path, scan(pdf_path), title, args.subject)
    size = pdf_path.stat().st_size
    page_count = pymupdf.open(pdf_path).page_count
    print(
        f"{pdf_path.name} written: {size / 1024:.0f} KB, {page_count} pages, "
        f"{entries} bookmarks",
        flush=True,
    )
    if pages:
        print(f"chapters on pages {pages}", flush=True)


if __name__ == "__main__":
    main()
