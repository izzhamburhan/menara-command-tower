#!/bin/sh
#
# worktree-cleanup.sh: remove git worktrees under .worktrees/ whose work is already merged,
# without ever losing local work.
#
# A worktree is removable when it has no uncommitted or untracked files and its branch (or,
# if detached, its commit) is already contained in the base branch (origin/<base> when there
# is an origin, else local <base>). Its local branch is deleted with `git branch -d`, which
# itself refuses unmerged branches. Remote branches are never touched.
#
# Usage:
#   sh scripts/worktree-cleanup.sh                dry run: list what would be removed and what is kept
#   sh scripts/worktree-cleanup.sh --apply        remove what the dry run lists
#   sh scripts/worktree-cleanup.sh --base main    base branch to compare with (default main)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
apply=0
base="main"
die() { echo "worktree-cleanup: $1" >&2; exit 2; }
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) apply=1 ;;
    --base) [ $# -ge 2 ] || die "--base needs a value"; base="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option '$1' (see --help)" ;;
  esac
  shift
done

common="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ||
  die "not inside a git repository"
top="${common%/.git}"

if git -C "$top" remote get-url origin >/dev/null 2>&1; then
  git -C "$top" fetch -q origin >/dev/null 2>&1 || echo "worktree-cleanup: fetch failed, using what is known locally" >&2
  ref="origin/$base"
else
  ref="$base"
fi
git -C "$top" rev-parse -q --verify "$ref^{commit}" >/dev/null || die "base '$ref' not found"

removed=0
kept=0
git -C "$top" worktree list --porcelain | awk '/^worktree /{print substr($0,10)}' | while IFS= read -r path; do
  case "$path" in "$top/.worktrees/"*) ;; *) continue ;; esac
  branch="$(git -C "$path" symbolic-ref -q --short HEAD 2>/dev/null)"
  head="$(git -C "$path" rev-parse HEAD)"
  label="${branch:-detached@$(echo "$head" | cut -c1-8)}"
  if [ -n "$(git -C "$path" status --porcelain)" ]; then
    echo "keep   $label: uncommitted or untracked files"; continue
  fi
  if ! git -C "$top" merge-base --is-ancestor "$head" "$ref"; then
    echo "keep   $label: not merged into $ref"; continue
  fi
  if [ "$apply" -eq 1 ]; then
    git -C "$top" worktree remove "$path" && echo "remove $label" &&
      { [ -z "$branch" ] || git -C "$top" branch -d "$branch" >/dev/null 2>&1 || true; }
  else
    echo "would remove $label ($path)"
  fi
done
git -C "$top" worktree prune
[ "$apply" -eq 1 ] || echo "(dry run; pass --apply to remove)"
