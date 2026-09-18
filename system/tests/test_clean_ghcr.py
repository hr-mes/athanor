"""Unit tests of forge/scripts/clean_ghcr.sh against an offline registry
(python3 -B -m unittest discover -s system/tests -v)."""

import json
import pathlib
import subprocess
import unittest

from test_kernel_artifacts import Tool

JANITOR = pathlib.Path(__file__).resolve().parents[2] / "forge" / "scripts" / "clean_ghcr.sh"


def version(id_, tags, day):
    return {"id": id_, "name": f"sha256:{id_:064x}", "created_at": f"2026-09-{day:02d}T00:00:00Z", "metadata": {"container": {"tags": tags}}}


class Janitor(Tool):
    def test_kernel_packages_are_never_touched(self):
        self.registry({"user_packages": ["azoth", "azoth-nvidia", "athanor-system"], "packages": {
            "azoth": [version(1, [], 1)],
            "azoth-nvidia": [version(2, [], 1)],
            "athanor-system": [version(3, ["101"], 1), version(4, ["102"], 2), version(5, ["103"], 3),
                               version(6, ["latest"], 0), version(7, [], 4)],
        }})
        r = subprocess.run(["bash", str(JANITOR), "hr-mes"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = [json.loads(line) for line in (self.dir / "calls.log").read_text().splitlines()]
        deleted = sorted(c[-1] for c in calls if "DELETE" in c)
        self.assertEqual(deleted, ["/users/hr-mes/packages/container/athanor-system/versions/3",
                                   "/users/hr-mes/packages/container/athanor-system/versions/7"])
        self.assertFalse(any("azoth" in " ".join(c) and "versions" in " ".join(c) for c in calls))


if __name__ == "__main__":
    unittest.main()
