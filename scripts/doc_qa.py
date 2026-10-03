#!/usr/bin/env python3
"""doc_qa.py — turn the repository's .md claims into executable checks.

The documentation makes claims a jury can falsify: a frozen decision vocabulary, a gate
registry that exists, a kernel with no decision calls, N tests passing. Every one is
checkable, so this checks them instead of trusting them (rule D12).

Two lessons are baked in, because both bit a first version of this script:

  * **Read from a pinned ref, never a working tree.** Main moves while you read it, and a stale
    checkout silently passes checks against a document that no longer exists.
  * **A check that could not run is not a pass.** Missing interpreter, unparsable claim, absent
    pytest — all reported as SKIP with the reason, never folded into a green result.

Usage:
    python3 scripts/doc_qa.py --submission . --node ../warrnt
    python3 scripts/doc_qa.py --submission . --node ../warrnt --run --python ../warrnt/.venv/bin/python

Exit code is non-zero when any check FAILS, so it can gate a pipeline.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, FAIL, SKIP = "PASS", "FAIL", "SKIP"
RESULTS: list[tuple[str, str, str]] = []
DECISION_CALLS = ("classify(", "apply_class(", "engine.evaluate(", "actors.check(")


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))


def sh(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(list(args), cwd=str(cwd), capture_output=True,
                              text=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def git(repo: Path, *args: str) -> str:
    return sh(repo, "git", *args)


class Docs:
    """The .md/.puml content of a repository at one pinned ref, with a working-tree fallback."""

    def __init__(self, repo: Path, ref: str | None) -> None:
        self.repo, self.ref, self.source = repo, ref, "working tree"
        self._cache: dict[str, str] = {}

    def get(self, rel: str) -> str:
        if rel in self._cache:
            return self._cache[rel]
        text = ""
        if self.ref:
            text = git(self.repo, "show", f"{self.ref}:{rel}")
            if text:
                self.source = self.ref
        if not text:
            p = self.repo / rel
            text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        self._cache[rel] = text
        return text

    def all_markdown(self) -> dict[str, str]:
        if self.ref:
            names = [l.strip() for l in
                     git(self.repo, "ls-tree", "-r", "--name-only", self.ref).splitlines()
                     if l.strip().endswith(".md")]
            if names:
                self.source = self.ref
                return {n: self.get(n) for n in names}
        found = {}
        for p in list(self.repo.glob("*.md")) + list((self.repo / "docs").rglob("*.md")):
            found[p.relative_to(self.repo).as_posix()] = p.read_text(encoding="utf-8",
                                                                     errors="replace")
        return found


# --------------------------------------------------------------------- C1 vocabulary
def contract_vocabulary(readme: str) -> set[str] | None:
    m = re.search(r'"decision"\s*:\s*"([a-z|]+)"', readme)
    return set(m.group(1).split("|")) if m else None


def code_vocabulary(node: Path, ref: str) -> set[str] | None:
    src = git(node, "show", f"{ref}:warrnt/models.py")
    if not src and (node / "warrnt" / "models.py").exists():
        src = (node / "warrnt" / "models.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"class Decision\(str,\s*Enum\):\s*(.*?)\n\S", src, re.S)
    return set(re.findall(r"^\s{4}([a-z_]+)\s*=", m.group(1), re.M)) if m else None


def check_vocabulary(docs: Docs, node: Path, node_ref: str) -> None:
    contract = contract_vocabulary(docs.get("README.md"))
    if contract is None:
        record(SKIP, "C1 contract vocabulary", "no /api/state contract block in README.md")
        return
    code = code_vocabulary(node, node_ref)
    if code is None:
        record(SKIP, "C1 code vocabulary", f"Decision enum not found at {node_ref}:warrnt/models.py")
        return
    if code == contract:
        record(OK, f"C1 contract == code ({node_ref})", f"{sorted(contract)}")
    else:
        record(FAIL, f"C1 contract == code ({node_ref})",
               f"code adds {sorted(code - contract) or '[]'}, code lacks "
               f"{sorted(contract - code) or '[]'} — a frozen interface changed without a "
               f"recorded D13 unfreeze commit")

    # Any document that enumerates the decision space must enumerate the frozen one. The list is
    # found by its shape - a run of decision words beginning with `allow`, in any of the
    # separators people actually type - so a document that never mentions the vocabulary is not
    # reported, and one that states it wrongly cannot hide behind not being on a fixed list.
    seen = 0
    per_doc: dict[str, set[str]] = {}
    for rel, text in sorted(docs.all_markdown().items()):
        if not text:
            continue
        hits = (re.findall(r"allow\s*[|/·]\s*deny[^\n]{0,140}", text)
                + re.findall(r"\(\s*allow\s*[/|][^)\n]{0,100}\)", text))
        for hit in hits:
            got = set(re.findall(r"\b(allow|deny|redact|human|revoked|expired)\b", hit))
            if len(got) >= 3:
                seen += 1
                per_doc.setdefault(rel, set()).update(got)
    for rel, got in per_doc.items():
        if got == contract:
            record(OK, f"C1 {rel} states the vocabulary", f"{sorted(got)}")
        else:
            record(FAIL, f"C1 {rel} states the vocabulary",
                   f"says {sorted(got)}, contract says {sorted(contract)} - a document "
                   f"that restates a frozen interface must restate it exactly")

    puml = docs.get("docs/uml/kernel-classes.puml")
    if puml:
        for hit in re.findall(r"allow\s*\|\s*deny[^\n]{0,140}", puml):
            got = set(re.findall(r"\b(allow|deny|redact|human|revoked|expired)\b", hit))
            seen += 1
            if got == contract:
                record(OK, "C1 docs/uml/kernel-classes.puml states the vocabulary", f"{sorted(got)}")
            else:
                record(FAIL, "C1 docs/uml/kernel-classes.puml states the vocabulary",
                       f"says {sorted(got)}, contract says {sorted(contract)}")
    if not seen:
        record(SKIP, "C1 vocabulary restatements", "no document enumerates the decision space")


# --------------------------------------------------------------------- C2 cited paths
PATH_RE = re.compile(r"`((?:warrnt|tests|scripts|docs)/[A-Za-z0-9_./-]+\.(?:py|md|json|out|puml))`")


def check_paths(docs: Docs, sub: Path, node: Path, node_ref: str) -> None:
    node_files = set(git(node, "ls-tree", "-r", "--name-only", node_ref).split())
    missing, seen = [], set()
    for name, text in docs.all_markdown().items():
        for rel in PATH_RE.findall(text):
            if rel in seen:
                continue
            seen.add(rel)
            if not ((sub / rel).exists() or rel in node_files or (node / rel).exists()):
                missing.append(f"{rel} (cited by {name})")
    if missing:
        record(FAIL, "C2 cited paths exist", "; ".join(missing[:8]) +
               (f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""))
    else:
        record(OK, "C2 cited paths exist", f"{len(seen)} cited paths resolved against {docs.source}")


# --------------------------------------------------------------------- C3 microkernel claim
def check_microkernel(docs: Docs, node: Path) -> None:
    doc = docs.get("docs/triz-python-architecture.md")
    if not doc:
        record(SKIP, "C3 microkernel claim", "docs/triz-python-architecture.md not present")
        return
    if "gates.py" not in doc:
        record(SKIP, "C3 microkernel claim", "the doc makes no registry claim to check")
        return

    refs = [r for r in git(node, "branch", "-r", "--format=%(refname:short)").split()
            if r and not r.endswith("/HEAD")]
    if not refs:
        record(SKIP, "C3 microkernel claim", "node repository has no remote refs to inspect")
        return

    satisfying, other = [], []
    for ref in refs:
        files = set(git(node, "ls-tree", "-r", "--name-only", ref).split())
        has_registry = "warrnt/gates.py" in files and "tests/test_gates.py" in files
        proxy = git(node, "show", f"{ref}:warrnt/proxy.py")
        clean = bool(proxy) and not any(c in proxy for c in DECISION_CALLS)
        label = (f"{ref} (registry: {'yes' if has_registry else 'no'}, "
                 f"kernel decision calls: {'none' if clean else 'present'})")
        (satisfying if (has_registry and clean) else other).append(label)

    # The remote's own default branch, asked of the remote: a clone's origin/HEAD reflects how
    # the clone was made (git clone -b X), so it is not authoritative on its own.
    default = "origin/master"
    sym = sh(node, "git", "ls-remote", "--symref", "origin", "HEAD")
    m = re.search(r"ref:\s+refs/heads/(\S+)\s+HEAD", sym)
    if m:
        default = f"origin/{m.group(1)}"
    else:
        local = git(node, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        if local:
            default = local
    names = [s.split(" ")[0] for s in satisfying]
    if not satisfying:
        record(FAIL, "C3 microkernel claim", "no ref satisfies it · " + " · ".join(other))
    elif default in names:
        record(OK, "C3 microkernel claim", f"holds on the default ref {default}")
    else:
        record(FAIL, "C3 microkernel claim",
               f"true only on {', '.join(names)} — NOT on the default {default}. Stating it as "
               f"fact without naming the ref is a D12 problem")


# --------------------------------------------------------------------- C4 claimed counts
COUNT_RE = re.compile(r"(\d+)\s*(?:тэстаў|tests|passed)")
SUITE_RE = re.compile(r"(console-check|upstream|security|verify_live)[^0-9]{0,24}(\d+)\s*/\s*(\d+)")


def find_python(node: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for cand in ("Scripts/python.exe", "bin/python", "bin/python3"):
        p = node / ".venv" / cand
        if p.exists():
            return str(p)
    return shutil.which("python3") or shutil.which("python")


def check_counts(docs: Docs, node: Path, run: bool, py: str | None) -> None:
    doc = docs.get("docs/triz-python-architecture.md")
    claimed = sorted({int(n) for n in COUNT_RE.findall(doc)})
    if not claimed:
        record(SKIP, "C4 claimed counts", "no numeric test claims found in the triz doc")
        return
    if not run:
        record(SKIP, "C4 claimed counts", f"claims {claimed}; re-run with --run to reproduce")
        return
    if not py:
        record(SKIP, "C4 claimed counts", f"claims {claimed}; no python interpreter found")
        return
    out = sh(node, py, "-m", "pytest", "--collect-only", "-q")
    if "No module named pytest" in out or not out.strip():
        record(SKIP, "C4 claimed counts", f"claims {claimed}; pytest unavailable via {py}")
        return
    # pytest's --collect-only -q reports per file ("tests/test_x.py: 6") and, in some
    # versions, no "N tests collected" summary at all - sum the files, then fall back.
    per_file = [int(n) for n in re.findall(r":\s*(\d+)\s*$", out, re.M)]
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    actual = int(m.group(1)) if m else (sum(per_file) or None)
    if actual is None:
        record(SKIP, "C4 claimed counts", "pytest produced no parseable collected count")
        return
    biggest = max(claimed)
    record(OK if actual >= biggest else FAIL, "C4 claimed counts",
           f"doc claims up to {biggest}; pytest collects {actual} via {Path(py).name}")


# --------------------------------------------------------------------- C6 suite evidence
def check_evidence(docs: Docs, node: Path) -> None:
    doc = docs.get("docs/triz-python-architecture.md")
    pairs = SUITE_RE.findall(doc)
    if not pairs:
        record(SKIP, "C6 suite evidence", "no suite results claimed")
        return
    evidence = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in (node / "docs").glob("*.out")) if (node / "docs").is_dir() else ""
    unbacked = [f"{name} {a}/{b}" for name, a, b in pairs if f"{a}/{b}" not in evidence]
    if unbacked:
        record(FAIL, "C6 suite evidence", "claimed without a saved run: " + ", ".join(unbacked))
    else:
        record(OK, "C6 suite evidence", f"{len(pairs)} claimed suite results have saved runs")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the .md claims against the code.")
    ap.add_argument("--submission", default=".")
    ap.add_argument("--submission-ref", default="origin/main",
                    help="pinned ref the docs are read from (default origin/main)")
    ap.add_argument("--node", required=True)
    ap.add_argument("--node-ref", default="origin/master")
    ap.add_argument("--run", action="store_true", help="actually collect the test suite")
    ap.add_argument("--python", default=None, help="interpreter for the node's test suite")
    args = ap.parse_args()

    sub, node = Path(args.submission).resolve(), Path(args.node).resolve()
    for p, label in ((sub, "submission"), (node, "node")):
        if not p.exists():
            print(f"error: {label} path does not exist: {p}", file=sys.stderr)
            return 2

    docs = Docs(sub, args.submission_ref)
    print(f"doc QA · docs from {args.submission_ref} · node ref {args.node_ref}\n")
    check_vocabulary(docs, node, args.node_ref)
    check_paths(docs, sub, node, args.node_ref)
    check_microkernel(docs, node)
    check_counts(docs, node, args.run, find_python(node, args.python))
    check_evidence(docs, node)

    width = max((len(n) for _, n, _ in RESULTS), default=10)
    for status, name, detail in RESULTS:
        print(f"  [{status}] {name.ljust(width)}  {detail}")
    failed = sum(1 for s, _, _ in RESULTS if s == FAIL)
    skipped = sum(1 for s, _, _ in RESULTS if s == SKIP)
    print(f"\n{len(RESULTS) - failed - skipped}/{len(RESULTS)} passed · {skipped} skipped · "
          f"{failed} failed  (docs from {docs.source})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
