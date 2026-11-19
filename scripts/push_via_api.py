"""Push local commits to GitHub through the API, because git's transport is dead.

`github.com:443` is unreachable from here (curl 52 "Connection was reset", ping
100% loss) while `api.github.com` answers 200, so `git push` cannot work and
`gh api` can. This replays commits on the server: for each one, take the
server's tree, replace the files that commit changed, commit against the
server's head, move the ref.

It refuses unless each resulting tree is byte-identical to the local commit's
tree. A push that silently dropped or mangled a file would be worse than no
push at all, and the commit sha differs anyway (the committer timestamp does
not survive), so the tree is the only trustworthy comparison.

    python scripts/push_via_api.py --repo OWNER/NAME --branch BRANCH
    python scripts/push_via_api.py ... --dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def gh(*args: str, stdin: str | None = None) -> dict:
    cmd = ["gh", "api", *args]
    if stdin is not None:
        cmd += ["--input", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace",
                         input=stdin if stdin is not None else None)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {out.stderr.strip()[:600]}")
    return json.loads(out.stdout) if out.stdout.strip() else {}


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], capture_output=True)
    if binary:
        return out.stdout
    return out.stdout.decode("utf-8", "replace").strip()


def commits_between(repo: str, remote_sha: str) -> list[str]:
    """Local commits whose content is not on the server yet, oldest first.

    Not ``remote..HEAD``: a commit replayed through this script gets a new sha,
    so the local history is no longer an ancestor chain of the server's. The
    honest question is "which tree is the server standing on", so the first
    local commit whose tree matches the server's head is already there, and the
    ones after it are pending.
    """
    remote_tree = gh(f"repos/{repo}/commits/{remote_sha}")["commit"]["tree"]["sha"]
    local = [c for c in git("rev-list", "--reverse", "HEAD").splitlines() if c]
    for index, commit in enumerate(local):
        if git("rev-parse", f"{commit}^{{tree}}") == remote_tree:
            return local[index + 1:]
    # The server's tree matches nothing local: either it is ahead or the
    # histories diverged. Either way every local commit is "pending" and the
    # per-commit parent check will refuse the first one.
    return local


def push_one(repo: str, branch: str, commit: str, dry_run: bool) -> str | None:
    """Replay one commit on the server. Returns the new remote sha."""
    parent = git("rev-parse", f"{commit}^")
    ref = gh(f"repos/{repo}/git/ref/heads/{branch}")
    remote_head = ref["object"]["sha"]
    subject = git("log", "-1", "--format=%s", commit)
    print(f"\n--- {commit[:12]} {subject}")
    print(f"    local parent {parent[:12]}  remote head {remote_head[:12]}")

    if remote_head == commit:
        print("    already there")
        return remote_head

    # The parent check compares TREES, not shas. A commit replayed through this
    # script gets a different sha (the committer timestamp does not survive), so
    # the next local commit's parent sha no longer matches the server's head
    # even though the content is exactly the one just pushed. Comparing the tree
    # is the honest test: "is the server standing where this commit expects?"
    remote_tree = gh(f"repos/{repo}/commits/{remote_head}")["commit"]["tree"]["sha"]
    parent_tree = git("rev-parse", f"{parent}^{{tree}}")
    if remote_tree != parent_tree:
        print(f"    REFUSED: the server is not at this commit's parent.")
        print(f"      server tree {remote_tree}")
        print(f"      parent tree {parent_tree}")
        print(f"    The branch moved somewhere else; reconcile by hand.")
        return None
    if remote_head != parent:
        print(f"    (parent content matches; sha differs because the previous")
        print(f"     commit was replayed through the API)")

    base_tree = remote_tree
    changed = [p for p in git("diff", "--name-only", parent, commit).splitlines() if p]

    entries = []
    for path in changed:
        blob = git("rev-parse", f"{commit}:{path}")
        if not blob:
            print(f"    {path}: deleted - this script does not replay deletions")
            return None
        mode = "100755" if git("ls-tree", commit, path).startswith("100755") else "100644"
        entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob})

    if dry_run:
        print(f"    would change {len(changed)} file(s) on base tree {base_tree[:12]}")
        for e in entries:
            print(f"      {e['mode']} {e['path']} {e['sha'][:12]}")
        return None

    # Upload any blob the server does not already have.
    for entry in entries:
        try:
            gh(f"repos/{repo}/git/blobs/{entry['sha']}")
        except RuntimeError:
            data = git("cat-file", "blob", entry["sha"], binary=True)
            made = gh(f"repos/{repo}/git/blobs", stdin=json.dumps({
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            }))
            if made["sha"] != entry["sha"]:
                print(f"    REFUSED: uploaded blob hash differs for {entry['path']}")
                return None

    tree = gh(f"repos/{repo}/git/trees", stdin=json.dumps({
        "base_tree": base_tree,
        "tree": entries,
    }))
    local_tree = git("rev-parse", f"{commit}^{{tree}}")
    if tree["sha"] != local_tree:
        print(f"    REFUSED: the new tree is not the local tree.")
        print(f"      server {tree['sha']}")
        print(f"      local  {local_tree}")
        return None

    message = git("log", "-1", "--format=%B", commit)
    author = git("log", "-1", "--format=%an|%ae|%aI", commit).split("|")
    body = {
        "message": message,
        "tree": tree["sha"],
        "parents": [remote_head],
    }
    if len(author) == 3:
        body["author"] = {"name": author[0], "email": author[1], "date": author[2]}
    made = gh(f"repos/{repo}/git/commits", stdin=json.dumps(body))

    gh(f"repos/{repo}/git/refs/heads/{branch}", "-X", "PATCH",
       stdin=json.dumps({"sha": made["sha"], "force": False}))
    print(f"    pushed -> {made['sha'][:12]}  (tree identical: {tree['sha'][:12]})")
    return made["sha"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="OWNER/NAME")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ref = gh(f"repos/{args.repo}/git/ref/heads/{args.branch}")
    remote_head = ref["object"]["sha"]
    print(f"repo   : {args.repo}")
    print(f"branch : {args.branch}")
    print(f"remote : {remote_head}")

    pending = commits_between(args.repo, remote_head)
    if not pending:
        print("nothing to push")
        return 0
    print(f"pending: {len(pending)} commit(s)")

    for commit in pending:
        if push_one(args.repo, args.branch, commit, args.dry_run) is None:
            if args.dry_run:
                continue
            print("\nSTOPPED - fix the refusal above and re-run.")
            return 2

    if args.dry_run:
        return 0

    final = gh(f"repos/{args.repo}/git/ref/heads/{args.branch}")["object"]["sha"]
    print(f"\nremote now : {final}")
    print(f"local      : {git('rev-parse', 'HEAD')}")
    same = git("rev-parse", "HEAD^{tree}") == gh(
        f"repos/{args.repo}/commits/{final}")["commit"]["tree"]["sha"]
    print(f"trees match: {same}")
    return 0 if same else 3


if __name__ == "__main__":
    raise SystemExit(main())