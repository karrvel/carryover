#!/usr/bin/env python3
# © 2026 karrvel — MIT License. See LICENSE.md.
"""Regression tests for pii-scan.py (stdlib unittest, throwaway git repos, no network).

Run from the kit root:  python3 -m unittest discover -s tooling/tests -v
"""
import os, subprocess, sys, tempfile, unittest

SCAN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pii-scan.py")
# Built at runtime: a literal would trip pii-scan on the kit's own tree, and an allow-listed one
# (@example.com) would be masked, so the test would pass without detecting anything.
LEAK = "leak" + "@" + "corp.test"
# Hermetic git: no global/system config, so no user hooks, signing or identity leak in.
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


class PiiScanNonUtf8(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.git("init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                       cwd=self.repo, env=ENV, check=True, capture_output=True)

    def stage(self, name, data):
        with open(os.path.join(self.repo, name), "wb") as fh:
            fh.write(data)
        self.git("add", name)

    def scan(self, *args):
        r = subprocess.run([sys.executable, SCAN, *args], cwd=self.repo, env=ENV,
                           capture_output=True, encoding="utf-8", errors="replace")
        self.assertNotIn("Traceback", r.stderr)
        return r

    def test_staged_latin1_leak_is_detected(self):
        self.stage("notes.txt", b"caf\xe9 contact: " + LEAK.encode() + b"\n")
        r = self.scan("--staged")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("staged diff", r.stdout)   # the path that used to crash actually ran
        self.assertIn(LEAK, r.stdout)

    def test_range_latin1_leak_is_detected(self):
        self.git("commit", "-q", "--allow-empty", "-m", "init")
        self.stage("notes.txt", b"caf\xe9 contact: " + LEAK.encode() + b"\n")
        self.git("commit", "-q", "-m", "add notes")
        r = self.scan("--range", "HEAD~1..HEAD")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("added lines in history", r.stdout)

    def test_staged_clean_non_utf8_and_binary_pass(self):
        self.stage("cp1251.txt", "привет, мир\n".encode("cp1251"))
        self.stage("blob.bin", b"\x00\xff\xfe binary \x00")
        r = self.scan("--staged")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
