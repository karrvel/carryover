#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""Tests for kb-lint.py's provenance-path warning (stdlib unittest, throwaway vault).

Run from the kit root:  python3 -m unittest discover -s tooling/tests -v
"""
import os, subprocess, sys, tempfile, unittest

LINT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb-lint.py")

# Real-world provenance shapes that are NOT paths, then two that resolve, then two that don't.
PROVENANCE = "; ".join([
    "2026-03-24 499f188504", "fleet audit 2026-08-11/12", "sessions 793e50b680/b03e68d597",
    "verified vs repos/app@808b824", "https://example.org/docs/page.html",
    "docs.example.org/guide/setup.md", "~/notes/x.md", "/etc/hosts.conf", "docker-compose*.yml",
    "Next.js/Turbopack and Next.js", ".env", "deploy.sh.j2:403",
    "src/real.py:42", "real-bare.md",           # exist under the root → quiet
    "app/layout.tsx", "next.config.ts",         # exist nowhere → warned
])


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class ProvenancePaths(unittest.TestCase):
    def test_only_missing_paths_warn_and_never_fail(self):
        with tempfile.TemporaryDirectory() as root:
            vault = os.path.join(root, "_knowledge")
            write(os.path.join(root, "repos", "app", "src", "real.py"), "")
            write(os.path.join(vault, "reference", "real-bare.md"), "")
            write(os.path.join(vault, "decisions", "ghost-stack.md"),
                  "---\nname: ghost-stack\ntype: decision\ntitle: Ghost stack\nstatus: active\n"
                  "updated: 2026-11-09\nvolatility: durable\narea: app\ntags: [t]\n"
                  f'provenance: "{PROVENANCE}"\n---\n\nBody.\n')
            r = subprocess.run([sys.executable, LINT], capture_output=True, text=True,
                               env=dict(os.environ, KB_ROOT=root, KB_VAULT=vault))
            warned = [ln for ln in r.stdout.splitlines() if "provenance cites" in ln]
            self.assertEqual(r.returncode, 0, r.stdout)          # a warning, never an error
            self.assertEqual(len(warned), 2, "\n".join(warned))
            self.assertIn("`app/layout.tsx`", warned[0])
            self.assertIn("`next.config.ts`", warned[1])


if __name__ == "__main__":
    unittest.main()
