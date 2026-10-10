#!/bin/sh
#
# worktree-add.sh: create a git worktree at <repo>/.worktrees/<name>, wherever you run it
# from. Use it instead of a raw `git worktree add` so several agents can work in parallel
# without sharing a checkout, and the path is always built from the repo's own top folder.
#
# Usage:
#   sh scripts/worktree-add.sh <branch> [--base main]   new branch from origin/<base> (or local <base> if no origin)
#   sh scripts/worktree-add.sh <branch> --existing      an existing branch (local, or origin/<branch> tracked)
#   sh scripts/worktree-add.sh <name> --detach <ref>    a read-only checkout at <ref>, e.g. for review
#
# Fetches origin first when there is one, refuses if .worktrees/ is not git-ignored, and
# prints `worktree: <absolute path>` as its last line. Running it again for a worktree that
# already exists just prints the path.

HERE="$(cd "$(dirname "$0")/.." && pwd)"
export GIT_TERMINAL_PROMPT=0

die() { echo "worktree-add: $1" >&2; exit 1; }
usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

[ $# -ge 1 ] || { usage >&2; exit 1; }
case "$1" in -h|--help) usage; exit 0 ;; esac
name="$1"; shift
mode="new"; base="main"; ref=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) [ $# -ge 2 ] || die "--base needs a value"; base="$2"; shift ;;
    --existing) mode="existing" ;;
    --detach) [ $# -ge 2 ] || die "--detach needs a ref"; mode="detach"; ref="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option '$1' (see --help)" ;;
  esac
  shift
done

case "$name" in
  ''|/*|*..*|*' '*|-*) die "invalid worktree name '$name' (no leading / or -, no .., no spaces)" ;;
esac

common="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ||
  die "not inside a git repository"
case "$common" in
  */.git) top="${common%/.git}" ;;
  *) die "unusual git layout ($common); create the worktree by hand" ;;
esac

git -C "$top" rev-parse -q --verify HEAD >/dev/null 2>&1 ||
  die "the repo has no commits yet; make an initial commit first"

git -C "$top" check-ignore -q .worktrees/ ||
  die ".worktrees/ is not git-ignored in $top; ask the developer before adding it to .gitignore"

dest="$top/.worktrees/$name"
if [ -e "$dest" ]; then
  if git -C "$top" worktree list --porcelain | grep -qxF "worktree $dest"; then
    echo "already exists: $dest"
    echo "worktree: $dest"
    exit 0
  fi
  die "$dest exists but is not a registered worktree; look at it before doing anything"
fi

has_origin=0
if git -C "$top" remote get-url origin >/dev/null 2>&1; then
  has_origin=1
  git -C "$top" fetch -q origin >/dev/null 2>&1 ||
    die "git fetch failed (if this is an agent sandbox, re-run outside it)"
fi

case "$mode" in
  new)
    git -C "$top" show-ref --verify -q "refs/heads/$name" &&
      die "branch '$name' already exists; use --existing to check it out"
    if [ "$has_origin" -eq 1 ] && git -C "$top" show-ref --verify -q "refs/remotes/origin/$base"; then
      start="origin/$base"
    elif git -C "$top" show-ref --verify -q "refs/heads/$base"; then
      start="$base"
    else
      die "base '$base' exists neither on origin nor locally"
    fi
    git -C "$top" worktree add -q --no-track -b "$name" "$dest" "$start" || die "git worktree add failed"
    echo "created $dest (new branch $name from $start)"
    ;;
  existing)
    if git -C "$top" show-ref --verify -q "refs/heads/$name"; then
      git -C "$top" worktree add -q "$dest" "$name" || die "git worktree add failed"
      echo "created $dest (existing branch $name)"
    elif git -C "$top" show-ref --verify -q "refs/remotes/origin/$name"; then
      git -C "$top" worktree add -q --track -b "$name" "$dest" "origin/$name" || die "git worktree add failed"
      echo "created $dest (branch $name tracking origin/$name)"
    else
      die "branch '$name' exists neither locally nor on origin"
    fi
    ;;
  detach)
    git -C "$top" rev-parse -q --verify "$ref^{commit}" >/dev/null ||
      die "ref '$ref' not found"
    git -C "$top" worktree add -q --detach "$dest" "$ref" || die "git worktree add failed"
    echo "created $dest (detached at $ref)"
    ;;
esac

echo "worktree: $dest"
