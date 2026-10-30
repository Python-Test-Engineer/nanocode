# skills/

Portable skill bundles kept in this repo so they can be exported and dropped
into any Hermes install.

## book-project-guide

The house rules for this book: what is generated vs. hand-written, what a
chapter folder is, the fixed section order of `chNN/EXPLAINER_chNN.md`, every
root file that must learn about a new chapter, and the build/verify loop. Written
for an agent joining the repo cold as well as one adding chapter 16.

```
book-project-guide/
  SKILL.md                        onboarding, invariants, chapter recipe, pitfalls
  references/chapter-template.md  copy-paste chapter + README skeleton, registration diff
  scripts/check_chapters.py       audits that every chapter is registered in the build/test files
```

```bash
# audit registration (from the repo root)
uv run python skills/book-project-guide/scripts/check_chapters.py .
```

## build-pictures

Turns every chapter's central ASCII diagram into a moving SVG, then wraps all of
them in the same single-file shell as `book.html` — sidebar picture TOC, filter,
scroll-spy, progress bar, copyable original ASCII, dark mode, print styles, the
**Aa** appearance panel, plus per-diagram **Replay** and a global **Pause
motion** control.

```
build-pictures/
  SKILL.md                         workflow, animation rules, verification, pitfalls
  scripts/build_pictures.py        extract ASCII + compose the animated page
  references/animation-recipes.md  SVG primitives, timing, and the 15 diagram patterns
```

```bash
# from the repository root; writes ./pictures.html
python skills/build-pictures/scripts/build_pictures.py --root .

# optional paths
python skills/build-pictures/scripts/build_pictures.py \
    --root . --book book.html --out pictures.html
```

The generator is stdlib-only. It reads the chapter `EXPLAINER_chNN.md` files and
`book.html`, so the animations stay in the same house style and the original
ASCII remains the source of truth.

## make-book

Turns a Markdown document into the same kind of single-file, two-pane guide as
this repo's `book.html` — sticky contents pane with filter and scroll-spy,
terracotta/serif house style, and the live **Aa** appearance panel (type,
layout, fonts, light/dark colours, Copy TOML).

```
make-book/
  SKILL.md                  when to use it, workflow, panel internals, pitfalls
  scripts/build_book.py     Markdown -> single-file HTML (CSS + JS inlined)
  assets/book_theme.toml    default theme: colours, fonts, sizes, layout
  references/theme-keys.md  every key, CSS variable and panel range
```

### Install

Copy the folder into a Hermes skills directory:

```bash
# this profile
cp -r skills/make-book ~/AppData/Local/hermes/skills/software-development/

# any other profile
cp -r skills/make-book <hermes-home>/profiles/<name>/skills/software-development/
```

Hermes picks it up on the next session (`skills_list` / `skill_view(make-book)`).

### Use without installing

The generator is standalone — Python 3.11+, `markdown` as the only dependency:

```bash
cd skills/make-book
uv run --with markdown python scripts/build_book.py --help

# rebuild this repo's book through the skill instead of build_book.py
cd ../..
uv run --with markdown python skills/make-book/scripts/build_book.py \
    --src EXPLAINER.md --out /tmp/book-skills.html --theme book_theme.toml \
    --title "Nanocode, explained" \
    --eyebrow "Build your own coding agent" \
    --subtitle "A chapter-by-chapter walkthrough for students."
```

`--theme` defaults to `book_theme.toml` in the working directory; start from
`assets/book_theme.toml` and edit, or open the built page and use **Copy TOML**.

### Export as an archive

```bash
cd skills && tar -czf make-book.tgz make-book     # or: zip -r make-book.zip make-book
```
