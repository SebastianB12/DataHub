"""Pytest wrapper around pipeline.validate_te_conformity.

Lives under tests/ so CI / pytest discovery picks it up. The actual logic
sits in pipeline/validate_te_conformity.py so that run_all.py can call the
same code without a pytest dependency.
"""
import subprocess
import sys


def test_te_conformity():
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.validate_te_conformity"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
