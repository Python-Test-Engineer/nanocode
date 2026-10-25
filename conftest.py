"""Root pytest configuration - lets one `pytest` run cover every chapter.

Every chapter is a standalone snapshot with the same file names:

    chNN/nanocode.py   chNN/llm.py   chNN/tools.py   chNN/ui.py
    chNN/test_nanocode.py

Eleven chapters therefore define eleven different modules called `nanocode`
(and eleven test files called `test_nanocode.py`), which a single pytest process
cannot import the usual way: the default import mode trips over the duplicate
test module name, and `from nanocode import ...` would resolve to whichever
chapter happened to be imported first - so every chapter after the first would
run the wrong agent.

So each chapter gets a private import root:

  * `pytest_collect_file` - before a test file is collected, its chapter
    directory goes to the front of sys.path, so the test module's
    `from nanocode import ...` picks up that chapter's files
  * `pytest_runtest_setup` - before each test *runs*, the chapter's modules are
    published into sys.modules again, so runtime lookups that go through a
    string (`monkeypatch.setattr("nanocode.DDGS", ...)`, `import nanocode`)
    also hit the right chapter, whatever order pytest collected in

Together with `--import-mode=importlib` (set in pyproject.toml) that makes

    uv run pytest            # 197 tests, 11 chapters, one process

work, in any order. `run_all_tests.py` still exists for the one-process-per-
chapter view the book uses (`cd ch09 && pytest`).
"""

import sys
from pathlib import Path

# Modules that exist once per chapter and must not leak between chapters.
# `hooks` is shared by every chapter from 03 on; `sounds` exists from ch13 on and
# `sandbox` from ch14 on (their absence in earlier chapters is why _bind swallows
# ImportError).
CHAPTER_MODULES = ("ui", "llm", "tools", "hooks", "sounds", "sandbox", "nanocode")

_bound = None  # the chapter directory currently published in sys.modules


def pytest_collectstart(collector):
    """Bind the chapter just before pytest imports a test module.

    `pytest_collect_file` is too late in one case: when test files are named on
    the command line, their modules can be imported before the hook runs for
    them, and the test module would bind whichever chapter was current. The
    collector that represents a module is created first and collected (imported)
    right after this hook fires, which is exactly the moment we need.
    """
    # Dir collectors also reach this hook; only a test module needs binding, and
    # its parent directory is the chapter.
    path = getattr(collector, "path", None)
    if path is not None and path.name.startswith("test_") and path.suffix == ".py":
        _bind(path.parent)


def pytest_runtest_setup(item):
    """Re-publish the owning chapter's modules before each test runs.

    Needed because tests do not only use what they imported at collection time:
    `monkeypatch.setattr("nanocode.DDGS", ...)` and `import nanocode` inside a
    test resolve through sys.modules at RUN time. Without this second binding,
    the last collected chapter would answer for all of them.
    """
    path = getattr(item, "path", None) or Path(str(item.fspath))
    _bind(Path(str(path)).parent)


def _bind(directory: Path):
    """Make `directory`'s nanocode/llm/tools/ui the ones sys.modules resolves to."""
    global _bound

    directory = Path(directory)
    if not (directory / "nanocode.py").exists():
        # Not a chapter (repo root, a shared test, ...): leave sys.path and
        # sys.modules alone rather than guessing.
        return

    if directory == _bound:
        return

    entry = str(directory)
    inserted = entry not in sys.path
    if inserted:
        sys.path.insert(0, entry)

    try:
        for name in CHAPTER_MODULES:
            sys.modules.pop(name, None)

        # Import in dependency order so the published modules are the chapter's own.
        for name in CHAPTER_MODULES:
            try:
                __import__(name)
            except ImportError:
                pass  # chapter 1 has no llm/tools, chapter 2 has no nanocode
    finally:
        # Remove the path entry again: the modules are already imported and
        # published, so a permanently growing sys.path would only hide mistakes.
        if inserted:
            sys.path.remove(entry)

    _bound = directory
