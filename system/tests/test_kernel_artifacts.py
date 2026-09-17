"""Unit tests of system/kernel-artifacts.sh against an offline registry
(python3 -B -m unittest discover -s system/tests -v)."""

import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = ROOT / "system" / "kernel-artifacts.sh"
PINS = dict(re.findall(r"^(\w+)=(.*)$", (ROOT / "forge/specs/azoth/pins.env").read_text(), re.M))
NVR = subprocess.run(["bash", str(ROOT / "forge/specs/azoth/nvr.sh")], capture_output=True, text=True, check=True).stdout.strip()
REG = "ghcr.io/hr-mes"
KERNEL = "sha256:" + "1" * 64
DEVEL = "sha256:" + "2" * 64
OTHER_KERNEL = "sha256:" + "9" * 64
MODULE = {"open": "sha256:" + "3" * 64, "legacy": "sha256:" + "4" * 64}
KERNEL_BUILD = "https://github.com/hr-mes/athanor/.github/workflows/kernel-build.yml@refs/heads/iso-v0"
KMOD = "https://github.com/hr-mes/athanor/.github/workflows/nvidia-kmod.yml@refs/heads/iso-v0"


def tag(branch, kernel=KERNEL):
    return f"{NVR}-k{kernel[7:19]}-{branch}-{PINS[f'NVIDIA_{branch.upper()}_VERSION']}"


def predicate(branch, kernel=KERNEL):
    return {"driver": branch, "version": PINS[f"NVIDIA_{branch.upper()}_VERSION"], "kernel": f"{NVR}.x86_64",
            "kernel_digest": kernel, "devel_digest": DEVEL,
            "pins": {k: v for k, v in PINS.items() if k.startswith("NVIDIA_")}}


def published(branches=("open", "legacy")):
    """A registry holding the signed kernel of the pins and the attested modules of BRANCHES."""
    fx = {
        "tags": {f"{REG}/azoth:{NVR}": KERNEL, f"{REG}/azoth-devel:{NVR}": DEVEL},
        "signatures": {f"{REG}/azoth@{KERNEL}": KERNEL_BUILD, f"{REG}/azoth-devel@{DEVEL}": KERNEL_BUILD},
        "attestations": {},
        "errors": [],
    }
    for branch in branches:
        ref = f"{REG}/azoth-nvidia@{MODULE[branch]}"
        fx["tags"][f"{REG}/azoth-nvidia:{tag(branch)}"] = MODULE[branch]
        fx["signatures"][ref] = KMOD
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": predicate(branch)}]
    return fx


class Tool(unittest.TestCase):
    """A temporary directory with the fakes on PATH, the artifacts directory and a git identity."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for tool in ("skopeo", "cosign", "gh"):
            (bin_dir / tool).symlink_to(HERE / "fake_registry.py")
        self.artifacts = self.dir / "artifacts"
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(self.dir), "RETRY_ATTEMPTS": "1",
            "KERNEL_ARTIFACTS_DIR": str(self.artifacts), "FAKE_REGISTRY": str(self.dir / "registry.json"),
            "FAKE_LOG": str(self.dir / "calls.log"), "GITHUB_REPOSITORY_OWNER": "hr-mes",
            "GITHUB_REPOSITORY": "hr-mes/athanor", "GITHUB_SERVER_URL": "https://github.com",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        }
        self.registry({})

    def tearDown(self):
        self.tmp.cleanup()

    def registry(self, fx):
        (self.dir / "registry.json").write_text(json.dumps(fx))

    def run_script(self, *args, cwd=None):
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=self.env, cwd=cwd or self.dir)

    def state_file(self):
        path = self.artifacts / "kernel-artifacts.env"
        return dict(line.split("=", 1) for line in path.read_text().splitlines()) if path.exists() else None


class Resolve(Tool):
    def test_ready_records_every_digest_and_the_tag_form(self):
        self.registry(published())
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.state_file()
        self.assertEqual(got["state"], "ready")
        self.assertEqual((got["kernel_digest"], got["devel_digest"]), (KERNEL, DEVEL))
        self.assertEqual((got["nvidia_open_digest"], got["nvidia_legacy_digest"]), (MODULE["open"], MODULE["legacy"]))
        self.assertEqual(got["nvidia_open_tag"], f"{NVR}-k{'1' * 12}-open-{PINS['NVIDIA_OPEN_VERSION']}")

    def test_missing_module_tag_is_modules_missing(self):
        self.registry(published(branches=("open",)))
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.state_file()
        self.assertEqual(got["state"], "modules-missing")
        self.assertEqual(got["nvidia_open_digest"], MODULE["open"])
        self.assertNotIn("nvidia_legacy_digest", got)
        self.assertEqual(got["nvidia_legacy_tag"], tag("legacy"))

    def test_absent_kernel_is_kernel_missing(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file(), {"state": "kernel-missing", "nvr": NVR, "registry": REG})

    def test_unsigned_kernel_is_kernel_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_absent_devel_is_kernel_missing(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth-devel:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_unsigned_devel_is_kernel_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth-devel@{DEVEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "kernel-missing")

    def test_kernel_tag_transport_error_fails(self):
        fx = published()
        fx["errors"].append(f"{REG}/azoth:{NVR}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("i/o timeout", r.stderr)
        self.assertIsNone(self.state_file())

    def test_transient_signature_error_is_not_folded_into_unsigned(self):
        fx = published()
        fx["signature_transient_errors"] = [f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("502 Bad Gateway", r.stderr)
        self.assertIsNone(self.state_file())

    def test_registry_error_fails_and_leaves_no_file(self):
        self.registry(published())
        self.assertEqual(self.run_script("resolve").returncode, 0)
        fx = published()
        fx["errors"].append(f"{REG}/azoth-nvidia:{tag('legacy')}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("i/o timeout", r.stderr)
        self.assertIsNone(self.state_file())

    def test_rekor_error_fails(self):
        fx = published()
        fx["errors"].append(f"{REG}/azoth-nvidia@{MODULE['open']}")
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 1)
        self.assertIn("502 Bad Gateway", r.stderr)
        self.assertIsNone(self.state_file())

    def test_unsigned_module_tag_is_modules_missing(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth-nvidia@{MODULE['legacy']}"]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_legacy_digest", self.state_file())

    def test_module_signed_by_another_workflow_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["signatures"][ref] = KERNEL_BUILD
        fx["attestations"][ref] = [{"identity": KERNEL_BUILD, "predicate": predicate("open")}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_module_signed_without_attestation_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["attestations"][ref] = []
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_wrong_driver_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        wrong = predicate("open")
        wrong["driver"] = "legacy"
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": wrong}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_another_kernel_digest_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": predicate("open", kernel=OTHER_KERNEL)}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_another_devel_digest_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        stale = predicate("open")
        stale["devel_digest"] = OTHER_KERNEL
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": stale}]
        self.registry(fx)
        r = self.run_script("resolve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["state"], "modules-missing")
        self.assertNotIn("nvidia_open_digest", self.state_file())

    def test_attestation_for_other_nvidia_pins_is_modules_missing(self):
        fx = published()
        ref = f"{REG}/azoth-nvidia@{MODULE['open']}"
        stale = predicate("open")
        stale["pins"]["NVIDIA_OPEN_COMMIT"] = "0" * 40
        fx["attestations"][ref] = [{"identity": KMOD, "predicate": stale}]
        self.registry(fx)
        self.assertEqual(self.run_script("resolve").returncode, 0)
        self.assertEqual(self.state_file()["state"], "modules-missing")

    def test_republished_kernel_fails_against_the_expected_digest(self):
        self.registry(published())
        r = self.run_script("resolve", "--expect-kernel-digest", OTHER_KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("republished", r.stderr)

    def test_republished_kernel_leaves_no_stale_file(self):
        self.registry(published())
        self.assertEqual(self.run_script("resolve").returncode, 0)
        self.assertIsNotNone(self.state_file())
        r = self.run_script("resolve", "--expect-kernel-digest", OTHER_KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_expect_kernel_digest_fails_when_kernel_becomes_absent(self):
        fx = published()
        del fx["tags"][f"{REG}/azoth:{NVR}"]
        self.registry(fx)
        r = self.run_script("resolve", "--expect-kernel-digest", KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_expect_kernel_digest_fails_when_kernel_becomes_unsigned(self):
        fx = published()
        del fx["signatures"][f"{REG}/azoth@{KERNEL}"]
        self.registry(fx)
        r = self.run_script("resolve", "--expect-kernel-digest", KERNEL)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.state_file())

    def test_require_ready(self):
        self.registry(published(branches=("open",)))
        self.assertEqual(self.run_script("require-ready").returncode, 1)
        self.registry(published())
        self.assertEqual(self.run_script("require-ready").returncode, 0)

    def test_get_and_has(self):
        self.registry(published(branches=("open",)))
        self.run_script("resolve")
        self.assertEqual(self.run_script("get", "kernel_digest").stdout.strip(), KERNEL)
        self.assertEqual(self.run_script("get", "nvidia_legacy_digest").returncode, 1)
        self.assertEqual(self.run_script("has", "nvidia_open_digest").returncode, 0)
        self.assertEqual(self.run_script("has", "nvidia_legacy_digest").returncode, 1)


class Repo(Tool):
    """A git repository with a bare origin and a shallow clone, as actions/checkout leaves it."""

    def setUp(self):
        super().setUp()
        self.origin = self.dir / "origin.git"
        self.work = self.dir / "work"
        self.git("init", "-q", "--bare", "-b", "iso-v0", str(self.origin), cwd=self.dir)
        self.git("clone", "-q", str(self.origin), str(self.work), cwd=self.dir)
        self.commit({"README.md": "x\n", "forge/specs/azoth/pins.env": "".join(f"{k}={v}\n" for k, v in PINS.items())})

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.work, env=self.env, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for rel, text in files.items():
            path = self.work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")
        self.git("push", "-q", "origin", "HEAD:iso-v0")
        return self.git("rev-parse", "HEAD")

    def shallow(self):
        """A depth-1 clone of origin, like the checkout of a push event."""
        clone = self.dir / "shallow"
        self.git("clone", "-q", "--depth=1", "-b", "iso-v0", f"file://{self.origin}", str(clone), cwd=self.dir)
        return clone

    def state(self, state, **extra):
        self.artifacts.mkdir(exist_ok=True)
        lines = {"state": state, "nvr": NVR, "registry": REG, **extra}
        (self.artifacts / "kernel-artifacts.env").write_text("".join(f"{k}={v}\n" for k, v in lines.items()))

    def pin_change(self, **pins):
        text = "".join(f"{k}={pins.get(k, v)}\n" for k, v in PINS.items())
        return {"forge/specs/azoth/pins.env": text}


class Cycle(Repo):
    def cycle(self, *args, cwd=None):
        return self.run_script("cycle", *args, cwd=cwd or self.shallow())

    def test_kernel_build_paths_match_the_workflow(self):
        text = (ROOT / ".github/workflows/kernel-build.yml").read_text()
        block = re.search(r"^  push:\n(?:    .*\n)*?    paths:\n((?:      - .*\n)+)", text, re.M).group(1)
        paths = [line.strip()[2:].replace("**", "*") for line in block.splitlines()]
        script = re.search(r"^KERNEL_BUILD_PATHS=\((.*)\)$", SCRIPT.read_text(), re.M).group(1)
        self.assertEqual(paths, re.findall(r"'([^']+)'", script))

    def test_ready_builds(self):
        self.state("ready")
        before = self.git("rev-parse", "HEAD")
        after = self.commit({"system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "build")

    def test_push_starting_kernel_build_defers_a_missing_kernel(self):
        self.state("kernel-missing")
        before = self.git("rev-parse", "HEAD")
        after = self.commit({**self.pin_change(FEDORA_KERNEL_NVR="7.2.6-100.fc43"), "system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "defer")
        self.assertIn("Kernel Build", r.stdout)

    def test_push_starting_kernel_build_defers_missing_modules(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        before = self.git("rev-parse", "HEAD")
        after = self.commit({".github/workflows/kernel-build.yml": "name: x\n", "system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "defer")

    def test_push_outside_kernel_build_with_missing_kernel_fails(self):
        self.state("kernel-missing")
        before = self.git("rev-parse", "HEAD")
        after = self.commit({"system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not start Kernel Build", r.stderr)
        self.assertNotIn("cycle", self.state_file())

    def test_push_outside_kernel_build_with_missing_modules_builds(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        before = self.git("rev-parse", "HEAD")
        after = self.commit({"system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "build")

    def test_push_without_previous_commit_and_missing_kernel_fails(self):
        self.state("kernel-missing")
        after = self.commit({"system/x": "1\n"})
        r = self.cycle("--event", "push", "--before", "0" * 40, "--after", after)
        self.assertEqual(r.returncode, 1)
        self.assertIn("previous commit", r.stderr)

    def test_dispatch_superseded_by_a_newer_push_defers(self):
        self.state("kernel-missing")
        r = self.cycle("--event", "workflow_dispatch", "--sha", "a" * 40, "--head", "b" * 40)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "defer")

    def test_dispatch_at_head_with_missing_kernel_fails(self):
        self.state("kernel-missing")
        r = self.cycle("--event", "workflow_dispatch", "--sha", "a" * 40, "--head", "a" * 40)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not published", r.stderr)

    def test_manual_dispatch_with_missing_modules_builds(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        r = self.cycle("--event", "workflow_dispatch", "--head", "a" * 40)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state_file()["cycle"], "build")

    def test_schedule_with_missing_kernel_fails(self):
        self.state("kernel-missing")
        self.assertEqual(self.cycle("--event", "schedule").returncode, 1)

    def test_cycle_rejects_an_unknown_event(self):
        self.state("ready")
        r = self.cycle("--event", "bogus", "--before", "a" * 40, "--after", "b" * 40)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--event", r.stderr)

    def test_ready_with_a_malformed_before_fails(self):
        # Argument shape is checked before the state is even read: state=ready must not mask
        # a caller bug.
        self.state("ready")
        r = self.cycle("--event", "push", "--before", "not-a-sha", "--after", "a" * 40)
        self.assertNotEqual(r.returncode, 0)

    def test_push_without_after_fails(self):
        self.state("ready")
        r = self.cycle("--event", "push", "--before", "a" * 40)
        self.assertNotEqual(r.returncode, 0)

    def test_dispatch_with_sha_but_empty_head_fails(self):
        self.state("kernel-missing")
        r = self.cycle("--event", "workflow_dispatch", "--sha", "a" * 40)
        self.assertNotEqual(r.returncode, 0)

    def test_dispatch_with_a_short_sha_fails(self):
        self.state("kernel-missing")
        r = self.cycle("--event", "workflow_dispatch", "--sha", "a" * 7, "--head", "a" * 7 + "0" * 33)
        self.assertNotEqual(r.returncode, 0)

    def test_cycle_write_replaces_a_stale_decision(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        before = self.git("rev-parse", "HEAD")
        after = self.commit({"system/x": "1\n"})
        r1 = self.cycle("--event", "push", "--before", before, "--after", after)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(self.state_file()["cycle"], "build")

        after2 = self.commit({".github/workflows/kernel-build.yml": "name: x\n"})
        clone2 = self.dir / "shallow2"
        self.git("clone", "-q", "--depth=1", "-b", "iso-v0", f"file://{self.origin}", str(clone2), cwd=self.dir)
        r2 = self.run_script("cycle", "--event", "push", "--before", after, "--after", after2, cwd=clone2)
        self.assertEqual(r2.returncode, 0, r2.stderr)

        text = (self.artifacts / "kernel-artifacts.env").read_text()
        self.assertEqual(text.count("cycle="), 1)
        self.assertEqual(self.run_script("get", "cycle").stdout.strip(), "defer")


class CheckPlan(Repo):
    def plan(self, files):
        self.commit(files)
        return self.run_script("check-plan", "--base", "HEAD^1", "--head", "HEAD", cwd=self.work)

    def test_ready_builds_three_images_with_the_delta(self):
        self.state("ready")
        r = self.plan({"system/x": "1\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.state_file()["check_gpus"], self.state_file()["check_delta"]), ("none nvidia nvidia-legacy", "true"))

    def test_kernel_pin_bump_skips_every_build(self):
        self.state("kernel-missing")
        r = self.plan({**self.pin_change(FEDORA_KERNEL_NVR="7.2.6-100.fc43"), "forge/specs/azoth/SOURCES/sources.sha256": "h\n", "forge/specs/azoth/KERNEL.md": "k\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.state_file()["check_gpus"], self.state_file()["check_delta"]), ("", "false"))
        self.assertIn("warning", r.stdout)

    def test_kernel_pin_bump_mixed_with_other_changes_fails(self):
        self.state("kernel-missing")
        r = self.plan({**self.pin_change(FEDORA_KERNEL_NVR="7.2.6-100.fc43"), "system/Containerfile": "FROM x\n"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("own pull request", r.stderr)

    def test_nvidia_pin_bump_builds_the_default_image(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        r = self.plan({**self.pin_change(NVIDIA_OPEN_VERSION="615.71.09"), "system/nvidia/locks/open.lock": "l\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.state_file()["check_gpus"], self.state_file()["check_delta"]), ("none", "true"))

    def test_missing_modules_with_unchanged_pins_fail(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        r = self.plan({"system/x": "1\n"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Orchestrator", r.stderr)

    def test_nvidia_and_kernel_pins_together_with_missing_modules_fail(self):
        self.state("modules-missing", kernel_digest=KERNEL)
        r = self.plan(self.pin_change(NVIDIA_OPEN_VERSION="615.71.09", CACHYOS_PATCHES_COMMIT="f" * 40))
        self.assertEqual(r.returncode, 1)

    def test_kernel_missing_with_only_nvidia_pins_moved_fails(self):
        # only_kernel_pins is true (the diff touches only pins.env, a KERNEL_PIN_FILES member),
        # but no kernel pin actually moved: that never explains a missing kernel.
        self.state("kernel-missing")
        r = self.plan(self.pin_change(NVIDIA_OPEN_VERSION="615.71.09"))
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
