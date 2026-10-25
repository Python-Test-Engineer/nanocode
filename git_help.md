# Git help: renaming a tag (local + remote)

Tag convention in this repo: all lowercase, `vX.Y.Z-<suffix>`:

    v1.0.0
    v1.1.0
    v1.2.0-explainers
    v1.3.0-book
    v1.4.0-book-customiser

Renames done:

    v6-book-customiser  -> v1.4.0-book-customiser   (2c965bb)
    v1.2.0-EXPLAINERS   -> v1.2.0-explainers        (5c4af08)
    v1.3.0-BOOK         -> v1.3.0-book              (16928f3)

There is no `git tag --rename`. You re-create the tag under the new name,
then delete the old one locally and on the remote.

## The commands used

    # 1. Create the new tag at the same commit as the old one
    git tag v1.4.0-book-customiser v6-book-customiser

    # 2. Delete the old tag locally
    git tag -d v6-book-customiser

    # 3. Push the new tag to the remote
    git push origin v1.4.0-book-customiser

    # 4. Delete the old tag on the remote
    git push origin --delete v6-book-customiser

For a case-only change, delete first and re-create from the saved hash
(see the Windows pitfall below):

    h=$(git rev-parse v1.3.0-BOOK)
    git tag -d v1.3.0-BOOK
    git tag v1.3.0-book "$h"
    git push origin v1.3.0-book
    git push origin --delete v1.3.0-BOOK

## Verify

    git tag -l                       # local tags
    git ls-remote --tags origin      # remote tags

Both should list the new names and no longer list the old ones.

## Notes

- These tags are lightweight (they point straight at a commit,
  `git cat-file -t <tag>` -> `commit`). `git tag <new> <old>` copies the ref
  exactly. If the old tag had been annotated, use
  `git tag -a <new> <old>^{} -m "message"` instead, otherwise the new tag
  becomes lightweight and loses the tagger/message.
- Pushing one tag by name (`git push origin <tag>`) is deliberate: a bare
  `git push --tags` will not delete the old tag remotely and can push unrelated
  local tags.
- `git push origin --delete <tag>` also works as
  `git push origin :refs/tags/<tag>`.
- Deleting and re-pushing a tag changes its ref for anyone who already fetched
  it. They must clean up on their side:

      git tag -d <old-tag>
      git fetch --prune --prune-tags

- To check what a tag points at before/after renaming:

      git log -1 --format='%H %s' v1.4.0-book-customiser

## Windows pitfall: case-only renames

`.git/refs/tags` sits on a case-insensitive filesystem on Windows, so creating
`v1.3.0-book` while `v1.3.0-BOOK` exists fails with:

    fatal: tag 'v1.3.0-book' already exists

Worse, `git rev-parse v1.3.0-book` resolves to the uppercase tag's commit, so it
looks like the rename already worked. It did not: the stored name is still
uppercase, so `git tag -l` and GitHub keep showing the old spelling. Delete the
old ref first, then re-create from the saved hash, and confirm with `git tag -l`
(not `git rev-parse`) that the stored names are lowercase.
