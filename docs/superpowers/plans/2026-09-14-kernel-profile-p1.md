# Kernel Profile P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver block P1 of the kernel and platform profile. It consists of:
- a typed manifest `profile.toml`;
- a validator that composes every role combination and generates the effective profiles;
- `athanor-profile-check`, which checks the settings already in force on the installed system;
- a required `profile-ok` marker in ISO acceptance.

**Architecture:** A new noarch package, `forge/specs/athanor-kernel-profile`, holds three things:
- the manifest;
- a repository tool, `kernel_profile.py`, which validates the manifest and writes one JSON file per allowed role combination into `SOURCES/`;
- the checker, installed as `/usr/bin/athanor-profile-check`.

The checker reads the JSON of the machine's role combination, which it derives from `athanor.role=` on `/proc/cmdline`. It compares that profile with `/proc/config.gz`, `/proc/sys` and `/sys/kernel/security`. CI runs the validator and the unit tests. ISO acceptance asks the installed guest to run the checker and requires its `PROFILE_OK` answer.

**Tech Stack:**
- Python 3.11 or later, standard library only: `tomllib`, `json`, `gzip`, `argparse`, `unittest`. The image ships `python3-3.14.6-1.fc43`; the GitHub runner `ubuntu-24.04` ships Python 3.12.
- An RPM spec (noarch).
- GitHub Actions.
- The ISO acceptance harness in `forge/test/iso`.

**Spec:** `docs/architecture/doc_kernel_profile.md` (approved at gate P0, revision 15), mainly sections 3, 7, 12 and 15.

## Global Constraints

- **Manifest (section 3):** "`athanor-kernel-profile/profile.toml` declares every setting of the base and of each role with its type and priority; a repository script generates the files, validates every role combination and computes the expected effective profile that the drift checker enforces."
- **Composition (section 7):** "Settings have types. Lists merge by union, maps merge recursively, scalars from two roles with different values are a build error unless one definition carries an explicit higher priority; numeric sysctls may declare an ordering (`max`, `min`) when the direction is obvious. Base settings marked locked cannot be overridden."
- **Fragments (section 7):** "Shared definitions live in manifest fragments that are not roles and cannot be activated alone."
- **Rejected combinations (section 7):** "A machine holding both an interactive role and the mesh role is an interactive mesh host … Until then the validator rejects the combination."
- **Role selection (section 7):** "Roles and the `user-modules` variant are selected with `athanor.role=` and `athanor.variant=`, which the validator declares." P1 reads `athanor.role=` only; the variant arrives in P6.
- **P1 row (section 15):** "`profile.toml`, validator, `athanor-profile-check` covering settings already in force; later blocks extend it | acceptance with `profile-ok`".
- **Out of P1:**
  - command line parameters (P3);
  - `scx_loader` state (P3, P5);
  - integrity mode and gating `boot-complete.target` (P4b);
  - roles against the PCR 12 event log (P5).
- **Project rules (CLAUDE.md):**
  - English on GitHub: commit messages, PR bodies, code comments and new documentation.
  - No `|| true`, no `continue-on-error`.
  - Logic lives in repository scripts; workflow `run:` blocks stay a few lines long.
  - Never prefix commands with `cd`.
  - Never push `forge/**` while an Orchestrator cycle runs.
  - Do not touch the Gatekeeper, attestation or `system/athanor-bus-api/src/polkit.rs`.
- **Bytecode:** run Python with `-B`, so no `__pycache__` directory lands in the tree.
- **Branch:** work on `kernel-profile-p1`, created from `origin/iso-v0`. Open pull requests into `iso-v0`.

## File Structure

| Path | Responsibility |
| --- | --- |
| `forge/specs/athanor-kernel-profile/kernel_profile.py` | Manifest loading, composition rules, role combinations, generation and `check` (repository tool, not installed) |
| `forge/specs/athanor-kernel-profile/profile.toml` | The manifest: the base settings already in force, the roles, the `interactive` fragment and the rejected combinations |
| `forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile/*.json` | Generated effective profiles, one per allowed combination (committed, and CI checks they are up to date) |
| `forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check` | The checker installed in the image |
| `forge/specs/athanor-kernel-profile/athanor-kernel-profile.spec` | The RPM |
| `forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py` | Unit tests of the tool and of the repository manifest |
| `forge/specs/athanor-kernel-profile/tests/test_check.py` | Unit tests of the checker against a fake root |
| `forge/config/packages.json` | Registers the package in the DAG (tier 1) |
| `.github/workflows/call-lint.yml` | Runs the validator and the unit tests in CI |
| `forge/test/iso/console.py`, `forge/test/iso/verdict.py`, `forge/test/iso/test_verdict.py` | The `PROFILE_PROBE` question, the `profile-ok` marker and the verdict that requires it |
| `NEXT.md` | The block group P entry |

---

### Task 1: Manifest composition tool

**Files:**
- Create: `forge/specs/athanor-kernel-profile/kernel_profile.py`
- Test: `forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in module `kernel_profile`:
  - `class ProfileError(Exception)`
  - `KINDS = ("kconfig", "sysctl", "runtime")`
  - `definitions(section: dict, where: str) -> dict[tuple[str, str], dict]`
  - `role_sections(manifest: dict, role: str) -> list[tuple[str, dict]]`
  - `effective(manifest: dict, combination: tuple[str, ...]) -> dict[tuple[str, str], dict]`, where each value is a definition dict with at least `value` and `decision`
  - `combinations(manifest: dict) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]`, returning `(allowed, refused)` with every tuple sorted by role name
  - `combination_name(combination: tuple[str, ...]) -> str`, which gives `"base"` for `()` and otherwise the role names joined by `+`
  - `render(manifest: dict, combination: tuple[str, ...]) -> str`, the JSON text
  - `build(manifest: dict) -> tuple[dict[str, str], list[tuple[str, ...]]]`, returning `({"<name>.json": text}, refused)`
  - `main(argv: list[str] | None = None) -> int`
- JSON document written per combination:

  ```json
  {"combination": "base", "roles": [], "schema": 1, "settings": {"kconfig": {"CONFIG_X": {"decision": "D4", "value": "y"}}, "runtime": {}, "sysctl": {}}}
  ```

- [ ] **Step 1: Write the failing tests**

Create `forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py`:

```python
"""Unit tests of kernel_profile.py: composition rules, role combinations and generation.

Run: python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v
"""

import io
import json
import pathlib
import sys
import tempfile
import textwrap
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
import kernel_profile as kp  # noqa: E402


def manifest(text: str) -> dict:
    return tomllib.loads(textwrap.dedent(text))


def value(settings: dict, kind: str, name: str):
    return settings[(kind, name)]["value"]


def run_tool(*args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = kp.main(list(args))
    return code, out.getvalue() + err.getvalue()


class Composition(unittest.TestCase):
    def test_base_only_manifest_has_one_combination(self) -> None:
        m = manifest(
            """
            schema = 1
            [base.sysctl]
            "kernel.kptr_restrict" = { value = "2", decision = "D47", locked = true }
            """
        )
        allowed, refused = kp.combinations(m)
        self.assertEqual(allowed, [()])
        self.assertEqual(refused, [])
        self.assertEqual(value(kp.effective(m, ()), "sysctl", "kernel.kptr_restrict"), "2")

    def test_role_overrides_an_unlocked_base_setting(self) -> None:
        m = manifest(
            """
            schema = 1
            [base.sysctl]
            "kernel.sysrq" = { value = 176, decision = "section 6" }
            [roles.mesh.sysctl]
            "kernel.sysrq" = { value = 0, decision = "section 7" }
            """
        )
        self.assertEqual(value(kp.effective(m, ()), "sysctl", "kernel.sysrq"), 176)
        mesh = kp.effective(m, ("mesh",))
        self.assertEqual(value(mesh, "sysctl", "kernel.sysrq"), 0)
        self.assertEqual(mesh[("sysctl", "kernel.sysrq")]["decision"], "section 7")

    def test_locked_base_setting_cannot_be_overridden(self) -> None:
        m = manifest(
            """
            schema = 1
            [base.sysctl]
            "kernel.kptr_restrict" = { value = "2", decision = "D47", locked = true }
            [roles.desktop.sysctl]
            "kernel.kptr_restrict" = { value = "1", decision = "test" }
            """
        )
        with self.assertRaisesRegex(kp.ProfileError, "locked"):
            kp.effective(m, ("desktop",))

    def test_roles_with_different_scalars_conflict(self) -> None:
        m = manifest(
            """
            schema = 1
            [roles.desktop.sysctl]
            "vm.swappiness" = { value = 60, decision = "test" }
            [roles.laptop.sysctl]
            "vm.swappiness" = { value = 10, decision = "test" }
            """
        )
        with self.assertRaisesRegex(kp.ProfileError, "priority"):
            kp.effective(m, ("desktop", "laptop"))

    def test_higher_priority_resolves_a_conflict(self) -> None:
        m = manifest(
            """
            schema = 1
            [roles.desktop.sysctl]
            "vm.swappiness" = { value = 60, decision = "test", priority = 10 }
            [roles.laptop.sysctl]
            "vm.swappiness" = { value = 10, decision = "test" }
            """
        )
        self.assertEqual(value(kp.effective(m, ("desktop", "laptop")), "sysctl", "vm.swappiness"), 60)

    def test_declared_ordering_resolves_numbers(self) -> None:
        m = manifest(
            """
            schema = 1
            [roles.desktop.sysctl]
            "vm.max_map_count" = { value = 65530, decision = "test", ordering = "max" }
            [roles.laptop.sysctl]
            "vm.max_map_count" = { value = 1048576, decision = "test", ordering = "max" }
            """
        )
        self.assertEqual(
            value(kp.effective(m, ("desktop", "laptop")), "sysctl", "vm.max_map_count"), 1048576
        )

    def test_lists_merge_by_union(self) -> None:
        m = manifest(
            """
            schema = 1
            [base.runtime]
            lsm = { value = ["lockdown", "yama"], decision = "section 5" }
            [roles.desktop.runtime]
            lsm = { value = ["yama", "ipe"], decision = "test" }
            """
        )
        self.assertEqual(
            value(kp.effective(m, ("desktop",)), "runtime", "lsm"), ["lockdown", "yama", "ipe"]
        )

    def test_maps_merge_recursively_and_still_conflict(self) -> None:
        merged = manifest(
            """
            schema = 1
            [roles.desktop.runtime]
            power = { value = { ac = "balanced" }, decision = "test" }
            [roles.laptop.runtime]
            power = { value = { battery = "power-saver" }, decision = "test" }
            """
        )
        self.assertEqual(
            value(kp.effective(merged, ("desktop", "laptop")), "runtime", "power"),
            {"ac": "balanced", "battery": "power-saver"},
        )
        conflicting = manifest(
            """
            schema = 1
            [roles.desktop.runtime]
            power = { value = { ac = "balanced" }, decision = "test" }
            [roles.laptop.runtime]
            power = { value = { ac = "performance" }, decision = "test" }
            """
        )
        with self.assertRaisesRegex(kp.ProfileError, "priority"):
            kp.effective(conflicting, ("desktop", "laptop"))

    def test_fragment_shared_by_two_roles_is_not_a_conflict(self) -> None:
        m = manifest(
            """
            schema = 1
            [fragments.interactive.sysctl]
            "kernel.warn_limit" = { value = 0, decision = "D19" }
            [roles.desktop]
            includes = ["interactive"]
            [roles.laptop]
            includes = ["interactive"]
            """
        )
        self.assertEqual(
            value(kp.effective(m, ("desktop", "laptop")), "sysctl", "kernel.warn_limit"), 0
        )

    def test_rejected_combinations_are_not_generated(self) -> None:
        m = manifest(
            """
            schema = 1
            [roles.desktop]
            [roles.mesh]
            [rules]
            rejected = [["desktop", "mesh"]]
            """
        )
        allowed, refused = kp.combinations(m)
        self.assertEqual(allowed, [(), ("desktop",), ("mesh",)])
        self.assertEqual(refused, [("desktop", "mesh")])
        files, _ = kp.build(m)
        self.assertEqual(sorted(files), ["base.json", "desktop.json", "mesh.json"])

    def test_malformed_manifests_fail(self) -> None:
        cases = (
            ('[base.kernel]\n"x" = { value = 1, decision = "t" }', "unknown kind"),
            ('[base.sysctl]\n"x" = { value = 1 }', "decision"),
            ('[base.sysctl]\n"x" = { value = 1, decision = "t", colour = "red" }', "unknown fields"),
            ('[roles.desktop.sysctl]\n"x" = { value = 1, decision = "t", locked = true }', "only base"),
            ('[roles.desktop]\nincludes = ["nope"]', "unknown fragment"),
            ('[rules]\nrejected = [["desktop", "ghost"]]\n[roles.desktop]', "unknown roles"),
        )
        for text, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(kp.ProfileError, message):
                    kp.build(manifest("schema = 1\n" + text))
        with self.assertRaisesRegex(kp.ProfileError, "schema"):
            kp.build(manifest("schema = 2\n"))


class Generation(unittest.TestCase):
    def test_generate_check_and_detect_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = pathlib.Path(name)
            source = tmp / "profile.toml"
            source.write_text(
                'schema = 1\n[base.sysctl]\n"kernel.dmesg_restrict" = { value = "1", decision = "D47" }\n'
                "[roles.desktop]\n"
            )
            out = tmp / "out"
            code, text = run_tool("generate", "--manifest", str(source), "--out", str(out))
            self.assertEqual(code, 0, text)
            self.assertEqual(sorted(p.name for p in out.glob("*.json")), ["base.json", "desktop.json"])
            base = json.loads((out / "base.json").read_text())
            self.assertEqual(base["settings"]["sysctl"]["kernel.dmesg_restrict"]["value"], "1")

            code, text = run_tool("check", "--manifest", str(source), "--out", str(out))
            self.assertEqual(code, 0, text)

            (out / "desktop.json").write_text("{}\n")
            code, text = run_tool("check", "--manifest", str(source), "--out", str(out))
            self.assertEqual(code, 1, text)
            self.assertIn("desktop.json", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v`

Expected: FAIL. The `test_kernel_profile` module errors with `ModuleNotFoundError: No module named 'kernel_profile'`.

- [ ] **Step 3: Write the implementation**

Create `forge/specs/athanor-kernel-profile/kernel_profile.py`:

```python
#!/usr/bin/env python3
"""The kernel profile manifest of Athanor: validation over every role combination and
generation of the effective profile that athanor-profile-check enforces.

Usage:
  kernel_profile.py generate [--manifest PATH] [--out DIR]
  kernel_profile.py check    [--manifest PATH] [--out DIR]

generate writes one JSON file per allowed role combination into DIR, by default the
package's SOURCES/usr/share/athanor/kernel-profile. check composes every combination and
fails on any composition error, and on generated files that differ from the manifest.

Specification: docs/architecture/doc_kernel_profile.md, sections 3, 7 and 12. Standard
library only (tomllib needs Python 3.11 or later), so it runs on the GitHub runner as is.
"""

import argparse
import itertools
import json
import pathlib
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "profile.toml"
OUT = HERE / "SOURCES" / "usr" / "share" / "athanor" / "kernel-profile"
SCHEMA = 1
KINDS = ("kconfig", "sysctl", "runtime")
FIELDS = {"value", "decision", "locked", "priority", "ordering"}
TOP_LEVEL = {"schema", "base", "fragments", "roles", "rules"}


class ProfileError(Exception):
    """A manifest that cannot be composed; the message names the setting and its sources."""


def definitions(section: dict, where: str) -> dict:
    """{(kind, name): definition} declared by one base, fragment or role section."""
    out = {}
    for kind, table in section.items():
        if kind == "includes":
            continue
        if kind not in KINDS:
            raise ProfileError(f"{where}: unknown kind {kind!r}, expected one of {', '.join(KINDS)}")
        if not isinstance(table, dict):
            raise ProfileError(f"{where}.{kind}: expected a table of settings")
        for name, definition in table.items():
            label = f"{where}.{kind}.{name}"
            if not isinstance(definition, dict) or "value" not in definition or "decision" not in definition:
                raise ProfileError(f"{label}: a setting needs a value and a decision")
            unknown = set(definition) - FIELDS
            if unknown:
                raise ProfileError(f"{label}: unknown fields {sorted(unknown)}")
            if definition.get("ordering") not in (None, "max", "min"):
                raise ProfileError(f"{label}: ordering must be max or min")
            if definition.get("locked") and where != "base":
                raise ProfileError(f"{label}: only base settings can be locked")
            out[(kind, name)] = definition
    return out


def shape(value) -> str:
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    if isinstance(value, (bool, int, float, str)):
        return "scalar"
    raise ProfileError(f"unsupported value {value!r}")


def union(first: list, second: list) -> list:
    merged = list(first)
    for item in second:
        if item not in merged:
            merged.append(item)
    return merged


def between_roles(label: str, first: tuple, second: tuple) -> tuple:
    """Two role or fragment definitions of one setting, merged; a conflict raises."""
    (first_where, first_def), (second_where, second_def) = first, second

    def merge(path: str, a, b):
        if shape(a) != shape(b):
            raise ProfileError(f"{path}: {first_where} sets a {shape(a)}, {second_where} a {shape(b)}")
        if shape(a) == "list":
            return union(a, b)
        if shape(a) == "map":
            merged = dict(a)
            for key, item in b.items():
                merged[key] = merge(f"{path}.{key}", a[key], item) if key in a else item
            return merged
        if a == b:
            return a
        a_priority, b_priority = first_def.get("priority", 0), second_def.get("priority", 0)
        if a_priority != b_priority:
            return a if a_priority > b_priority else b
        ordering = first_def.get("ordering")
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, b))
        if ordering and ordering == second_def.get("ordering") and numbers:
            return max(a, b) if ordering == "max" else min(a, b)
        raise ProfileError(
            f"{path}: {first_where} sets {a!r} and {second_where} sets {b!r}; give one "
            "definition a higher priority or declare the same ordering on both"
        )

    merged = dict(first_def)
    merged["value"] = merge(label, first_def["value"], second_def["value"])
    merged["priority"] = max(first_def.get("priority", 0), second_def.get("priority", 0))
    return f"{first_where} and {second_where}", merged


def over_base(label: str, base_def: dict, role_where: str, role_def: dict) -> dict:
    """A role definition applied over the base: lists extend, maps merge, scalars replace,
    and a locked base setting refuses any change."""

    def apply(path: str, base, role):
        if shape(base) != shape(role):
            raise ProfileError(f"{path}: base sets a {shape(base)}, {role_where} a {shape(role)}")
        if shape(base) == "list":
            return union(base, role)
        if shape(base) == "map":
            merged = dict(base)
            for key, item in role.items():
                merged[key] = apply(f"{path}.{key}", base[key], item) if key in base else item
            return merged
        return role

    value = apply(label, base_def["value"], role_def["value"])
    if value == base_def["value"]:
        return base_def
    if base_def.get("locked"):
        raise ProfileError(f"{label}: locked in base, and {role_where} changes it to {value!r}")
    return {**base_def, "value": value, "decision": role_def["decision"]}


def role_sections(manifest: dict, role: str) -> list:
    """[(where, section)] a role contributes: its fragments first, then its own section."""
    roles = manifest.get("roles", {})
    fragments = manifest.get("fragments", {})
    if role not in roles:
        raise ProfileError(f"unknown role {role!r}")
    sections = []
    for fragment in roles[role].get("includes", []):
        if fragment not in fragments:
            raise ProfileError(f"roles.{role}: unknown fragment {fragment!r}")
        if "includes" in fragments[fragment]:
            raise ProfileError(f"fragments.{fragment}: a fragment cannot include others")
        sections.append((f"fragments.{fragment}", fragments[fragment]))
    sections.append((f"roles.{role}", roles[role]))
    return sections


def effective(manifest: dict, combination: tuple) -> dict:
    """{(kind, name): definition} in force for a role combination."""
    base = definitions(manifest.get("base", {}), "base")
    contributions: dict = {}
    visited = set()
    for role in combination:
        for where, section in role_sections(manifest, role):
            if where in visited:
                continue
            visited.add(where)
            for key, definition in definitions(section, where).items():
                contributions.setdefault(key, []).append((where, definition))
    result = dict(base)
    for key, sources in contributions.items():
        label = f"{key[0]}.{key[1]}"
        where, definition = sources[0]
        for other in sources[1:]:
            where, definition = between_roles(label, (where, definition), other)
        result[key] = over_base(label, base[key], where, definition) if key in base else definition
    return result


def combinations(manifest: dict) -> tuple:
    """(allowed, refused): every subset of the roles, sorted, split by rules.rejected."""
    roles = sorted(manifest.get("roles", {}))
    rules = manifest.get("rules", {})
    unknown_rules = set(rules) - {"rejected"}
    if unknown_rules:
        raise ProfileError(f"rules: unknown fields {sorted(unknown_rules)}")
    rejected = [frozenset(pair) for pair in rules.get("rejected", [])]
    for pair in rejected:
        unknown = pair - set(roles)
        if unknown:
            raise ProfileError(f"rules.rejected names unknown roles {sorted(unknown)}")
    allowed, refused = [], []
    for size in range(len(roles) + 1):
        for combination in itertools.combinations(roles, size):
            if any(pair <= set(combination) for pair in rejected):
                refused.append(combination)
            else:
                allowed.append(combination)
    return allowed, refused


def combination_name(combination: tuple) -> str:
    return "+".join(combination) if combination else "base"


def render(manifest: dict, combination: tuple) -> str:
    """The effective profile of one combination, as the JSON text the checker reads."""
    name = combination_name(combination)
    try:
        settings = effective(manifest, combination)
    except ProfileError as error:
        raise ProfileError(f"combination {name}: {error}") from None
    document = {
        "schema": SCHEMA,
        "combination": name,
        "roles": list(combination),
        "settings": {kind: {} for kind in KINDS},
    }
    for (kind, setting), definition in sorted(settings.items()):
        document["settings"][kind][setting] = {
            "value": definition["value"],
            "decision": definition["decision"],
        }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def build(manifest: dict) -> tuple:
    """({file name: JSON text} for every allowed combination, refused combinations)."""
    if manifest.get("schema") != SCHEMA:
        raise ProfileError(f"schema must be {SCHEMA}")
    unknown = set(manifest) - TOP_LEVEL
    if unknown:
        raise ProfileError(f"unknown top-level tables {sorted(unknown)}")
    allowed, refused = combinations(manifest)
    files = {f"{combination_name(c)}.json": render(manifest, c) for c in allowed}
    return files, refused


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and generate the Athanor kernel profile.")
    parser.add_argument("command", choices=("check", "generate"))
    parser.add_argument("--manifest", type=pathlib.Path, default=MANIFEST)
    parser.add_argument("--out", type=pathlib.Path, default=OUT)
    args = parser.parse_args(argv)

    try:
        with open(args.manifest, "rb") as handle:
            manifest = tomllib.load(handle)
        files, refused = build(manifest)
    except (OSError, tomllib.TOMLDecodeError, ProfileError) as error:
        print(f"kernel_profile: {error}", file=sys.stderr)
        return 1

    if args.command == "generate":
        args.out.mkdir(parents=True, exist_ok=True)
        for old in args.out.glob("*.json"):
            if old.name not in files:
                old.unlink()
        for name, text in files.items():
            (args.out / name).write_text(text)
        print(f"kernel_profile: wrote {len(files)} combinations to {args.out}")
        return 0

    for combination in refused:
        print(f"kernel_profile: rejected combination {combination_name(combination)} (rules.rejected)")
    present = {path.name for path in args.out.glob("*.json")} if args.out.is_dir() else set()
    stale = sorted(
        name
        for name, text in files.items()
        if not (args.out / name).is_file() or (args.out / name).read_text() != text
    )
    stale += sorted(present - set(files))
    if stale:
        print(
            "kernel_profile: generated files differ from the manifest, run "
            "`python3 -B forge/specs/athanor-kernel-profile/kernel_profile.py generate`: "
            + ", ".join(stale),
            file=sys.stderr,
        )
        return 1
    print(f"kernel_profile: {len(files)} combinations valid, generated files up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v`

Expected: `Ran 12 tests` … `OK`.

- [ ] **Step 5: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/athanor-kernel-profile/kernel_profile.py forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py
git -C /var/home/hr-mes/athanor commit -m "feat(kernel-profile): compose the profile manifest over every role combination" -m "kernel_profile.py implements the composition rules of doc_kernel_profile.md section 7 and generates one effective profile per allowed combination."
```

---

### Task 2: The P1 manifest, generated profiles and CI

**Files:**
- Create: `forge/specs/athanor-kernel-profile/profile.toml`
- Create (generated): `forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile/{base,desktop,laptop,mesh,desktop+laptop}.json`
- Modify: `forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py` (append one test)
- Modify: `.github/workflows/call-lint.yml` (append one step)

**Interfaces:**
- Consumes: `kernel_profile.main`, `kernel_profile.build` (Task 1).
- Produces: the five JSON files that Task 3's repository test and the package read. `base.json` holds 25 settings: 20 `kconfig`, 3 `sysctl` and 2 `runtime`.

- [ ] **Step 1: Write the failing repository test**

Append to class `Generation` in `forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py`, before the `if __name__` line:

```python
    def test_repository_manifest_is_valid_and_generated(self) -> None:
        code, text = run_tool("check")
        self.assertEqual(code, 0, text)
        self.assertIn("rejected combination desktop+mesh", text)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v -k repository`

Expected: FAIL, with `kernel_profile: [Errno 2] No such file or directory: '.../profile.toml'` in the assertion message.

- [ ] **Step 3: Write the manifest**

Every value below was read on the running image on 2026-09-14. The kernel values come from `/proc/config.gz`, the sysctls from `sysctl -n`, `lockdown` from `/sys/kernel/security/lockdown` (`none [integrity] confidentiality`) and `lsm` from `/sys/kernel/security/lsm` (`lockdown,capability,yama,selinux,bpf,landlock,ipe,ima,evm`). Settings the profile wants but that are not in force today are left out on purpose; later blocks add them.

Create `forge/specs/athanor-kernel-profile/profile.toml`:

```toml
# The kernel profile manifest of Athanor (docs/architecture/doc_kernel_profile.md,
# sections 3 and 7). Every setting carries its value and the decision or section that
# motivates it; `locked` (base only), `priority` and `ordering` ("max" or "min") follow
# the composition rules of section 7. kernel_profile.py composes every role combination
# and writes the effective profiles to SOURCES/usr/share/athanor/kernel-profile.
#
# Block P1 declares the settings of the profile that are already in force on the image;
# later blocks extend the manifest as they deliver the rest.
schema = 1

# One kernel binary for every role (D1): a build option is never a role setting, so
# every kconfig entry is locked.
[base.kconfig]
CONFIG_MODULE_SIG_FORCE = { value = "y", decision = "section 5", locked = true }
CONFIG_CFI = { value = "y", decision = "section 5", locked = true }
CONFIG_RUST = { value = "y", decision = "D4", locked = true }
CONFIG_SCHED_BORE = { value = "y", decision = "D5", locked = true }
CONFIG_X86_64_VERSION = { value = "1", decision = "D14", locked = true }
CONFIG_PREEMPT_DYNAMIC = { value = "y", decision = "D13", locked = true }
CONFIG_PREEMPT_LAZY = { value = "y", decision = "D13", locked = true }
CONFIG_HZ = { value = "1000", decision = "section 6", locked = true }
CONFIG_DEFAULT_TCP_CONG = { value = '"bbr3"', decision = "section 6", locked = true }
CONFIG_SECURITY_IPE = { value = "y", decision = "D8", locked = true }
CONFIG_SECURITY_LANDLOCK = { value = "y", decision = "section 10", locked = true }
CONFIG_BPF_LSM = { value = "y", decision = "section 5", locked = true }
CONFIG_IMA_ARCH_POLICY = { value = "y", decision = "section 5", locked = true }
CONFIG_INTEGRITY_CA_MACHINE_KEYRING_MAX = { value = "y", decision = "D40", locked = true }
CONFIG_IA32_EMULATION = { value = "y", decision = "section 5", locked = true }
CONFIG_MODIFY_LDT_SYSCALL = { value = "y", decision = "section 5", locked = true }
CONFIG_SHUFFLE_PAGE_ALLOCATOR = { value = "y", decision = "section 5", locked = true }
CONFIG_DRM_PANIC = { value = "y", decision = "section 11", locked = true }
CONFIG_BTRFS_FS = { value = "y", decision = "D17", locked = true }
CONFIG_EROFS_FS = { value = "y", decision = "section 5", locked = true }

[base.sysctl]
"kernel.kptr_restrict" = { value = "2", decision = "D47", locked = true }
"kernel.dmesg_restrict" = { value = "1", decision = "D47", locked = true }
"net.core.default_qdisc" = { value = "fq", decision = "section 6", locked = true }

[base.runtime]
# The lockdown level selected in /sys/kernel/security/lockdown.
lockdown = { value = "integrity", decision = "section 5", locked = true }
# LSMs that must be active; others (capability, ima, evm) may be present as well.
lsm = { value = ["lockdown", "yama", "selinux", "bpf", "landlock", "ipe"], decision = "section 5" }

# Shared by desktop and laptop (D18); settings arrive with block P5.
[fragments.interactive]

[roles.desktop]
includes = ["interactive"]

[roles.laptop]
includes = ["interactive"]

[roles.mesh]

[rules]
# An interactive role together with the mesh role waits for the mesh specification
# (section 7, D27).
rejected = [["desktop", "mesh"], ["laptop", "mesh"]]
```

- [ ] **Step 4: Generate the profiles**

Run: `python3 -B forge/specs/athanor-kernel-profile/kernel_profile.py generate`

Expected: `kernel_profile: wrote 5 combinations to /var/home/hr-mes/athanor/forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile`

Run: `ls forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile/ && python3 -B -c 'import json; d=json.load(open("forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile/base.json")); print(d["combination"], {k: len(v) for k, v in d["settings"].items()})'`

Expected:
```
base.json  desktop+laptop.json  desktop.json  laptop.json  mesh.json
base {'kconfig': 20, 'runtime': 2, 'sysctl': 3}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v`

Expected: `Ran 13 tests` … `OK`.

- [ ] **Step 6: Run the validator in CI**

In `.github/workflows/call-lint.yml`, append this step after the existing `Structural checks (scripts/verify.py workflows)` step, at the same indentation:

```yaml
      - name: Kernel profile manifest and checker (kernel_profile.py check, unit tests)
        run: |
          set -euo pipefail
          python3 -B forge/specs/athanor-kernel-profile/kernel_profile.py check
          python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v
```

Run: `python3 -B forge/specs/athanor-kernel-profile/kernel_profile.py check`

Expected:
```
kernel_profile: rejected combination desktop+mesh (rules.rejected)
kernel_profile: rejected combination laptop+mesh (rules.rejected)
kernel_profile: rejected combination desktop+laptop+mesh (rules.rejected)
kernel_profile: 5 combinations valid, generated files up to date
```

Run: `grep -c 'kernel_profile.py check' .github/workflows/call-lint.yml`

Expected: `1`. The actionlint run in the Lint job of the pull request is the syntax gate for the workflow.

- [ ] **Step 7: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/athanor-kernel-profile/profile.toml forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile forge/specs/athanor-kernel-profile/tests/test_kernel_profile.py .github/workflows/call-lint.yml
git -C /var/home/hr-mes/athanor commit -m "feat(kernel-profile): declare the settings already in force and check them in CI" -m "profile.toml holds the base kernel configuration, sysctls and runtime state of block P1, the roles and the rejected interactive plus mesh combinations. The generated profiles are committed, and the lint workflow fails when they drift from the manifest."
```

---

### Task 3: athanor-profile-check

**Files:**
- Create: `forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check`
- Test: `forge/specs/athanor-kernel-profile/tests/test_check.py`

**Interfaces:**
- Consumes: the JSON document format of Task 1 (`settings.kconfig|sysctl|runtime.<name>.value`) and `base.json` of Task 2.
- Produces:
  - **Command:** `athanor-profile-check [--root DIR] [--profiles DIR] [--quiet]`. Exit status 0 when every setting holds, 1 on drift, 2 when the profile cannot be read or validated (unknown schema, empty or malformed `settings`, an unreadable `/proc/config.gz`) or an `athanor.role=` value on `/proc/cmdline` is malformed or the reserved name `base`.
  - **Output without `--quiet`:** one `DRIFT <kind>.<name>: expected <repr>, found <repr>` line per drift, then `athanor-profile-check: <combination>: <held>/<total> settings hold`.
  - **Module functions** (the tests load the file as a module): `main(argv) -> int`, `active_roles(root) -> list[str]`, `validate(document) -> dict`, `compare(root, settings) -> list[tuple[str, object, object]]`. Module constants `SCHEMA = 1` and `KINDS = ("kconfig", "sysctl", "runtime")`, the latter asserted equal to `kernel_profile.KINDS` by a CI guard test.

- [ ] **Step 1: Write the failing tests**

Create `forge/specs/athanor-kernel-profile/tests/test_check.py`:

```python
"""Unit tests of athanor-profile-check against a fake root.

Run: python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v
"""

import gzip
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
CHECKER = PACKAGE / "SOURCES" / "usr" / "bin" / "athanor-profile-check"
PROFILES = PACKAGE / "SOURCES" / "usr" / "share" / "athanor" / "kernel-profile"


def load_checker():
    loader = SourceFileLoader("athanor_profile_check", str(CHECKER))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


check = load_checker()


class FakeSystem:
    """A root directory holding the files athanor-profile-check reads."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.write("proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=1 rw\n")
        self.config([])
        self.write("sys/kernel/security/lockdown", "none [integrity] confidentiality\n")
        self.write(
            "sys/kernel/security/lsm", "lockdown,capability,yama,selinux,bpf,landlock,ipe,ima,evm"
        )

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def config(self, lines: list) -> None:
        path = self.root / "proc" / "config.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as handle:
            handle.write("\n".join(lines) + "\n")

    def sysctl(self, name: str, value) -> None:
        self.write("proc/sys/" + name.replace(".", "/"), f"{value}\n")


def profile(directory: pathlib.Path, name: str, settings: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    full = {"kconfig": {}, "sysctl": {}, "runtime": {}}
    for kind, values in settings.items():
        full[kind] = {key: {"value": value, "decision": "test"} for key, value in values.items()}
    document = {"schema": 1, "combination": name, "roles": [], "settings": full}
    (directory / f"{name}.json").write_text(json.dumps(document))


def run(root: pathlib.Path, profiles: pathlib.Path, *extra: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = check.main(["--root", str(root), "--profiles", str(profiles), *extra])
    return code, out.getvalue() + err.getvalue()


class Checker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.system = FakeSystem(pathlib.Path(self.tmp.name) / "root")
        self.profiles = pathlib.Path(self.tmp.name) / "profiles"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_every_setting_holds(self) -> None:
        self.system.config(["CONFIG_RUST=y", 'CONFIG_DEFAULT_TCP_CONG="bbr3"'])
        self.system.sysctl("kernel.kptr_restrict", 2)
        profile(
            self.profiles,
            "base",
            {
                "kconfig": {"CONFIG_RUST": "y", "CONFIG_DEFAULT_TCP_CONG": '"bbr3"'},
                "sysctl": {"kernel.kptr_restrict": "2"},
                "runtime": {"lockdown": "integrity", "lsm": ["lockdown", "yama", "ipe"]},
            },
        )
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 0, text)
        self.assertIn("base: 5/5 settings hold", text)

    def test_sysctl_drift_is_reported(self) -> None:
        self.system.sysctl("kernel.kptr_restrict", 0)
        profile(self.profiles, "base", {"sysctl": {"kernel.kptr_restrict": "2"}})
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 1, text)
        self.assertIn("DRIFT sysctl.kernel.kptr_restrict: expected '2', found '0'", text)
        self.assertIn("base: 0/1 settings hold", text)

    def test_option_that_is_not_set_reads_as_n(self) -> None:
        self.system.config(["# CONFIG_LOCK_DOWN_KERNEL_FORCE_INTEGRITY is not set"])
        profile(self.profiles, "base", {"kconfig": {"CONFIG_LOCK_DOWN_KERNEL_FORCE_INTEGRITY": "y"}})
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 1, text)
        self.assertIn("found 'n'", text)

    def test_missing_lsm_is_drift_and_extra_lsms_are_not(self) -> None:
        profile(self.profiles, "base", {"runtime": {"lsm": ["lockdown", "tomoyo"]}})
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 1, text)
        self.assertIn("DRIFT runtime.lsm", text)

    def test_quiet_prints_nothing(self) -> None:
        self.system.sysctl("kernel.kptr_restrict", 0)
        profile(self.profiles, "base", {"sysctl": {"kernel.kptr_restrict": "2"}})
        code, text = run(self.system.root, self.profiles, "--quiet")
        self.assertEqual(code, 1)
        self.assertEqual(text, "")

    def test_roles_on_the_command_line_select_their_profile(self) -> None:
        self.system.write("proc/cmdline", "root=UUID=1 athanor.role=laptop athanor.role=desktop\n")
        profile(self.profiles, "desktop+laptop", {"runtime": {"lockdown": "integrity"}})
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 0, text)
        self.assertIn("desktop+laptop: 1/1 settings hold", text)

    def test_missing_profile_cannot_be_checked(self) -> None:
        code, text = run(self.system.root, self.profiles)
        self.assertEqual(code, 2, text)
        self.assertIn("cannot check the profile", text)

    def test_repository_base_profile_holds_on_a_matching_system(self) -> None:
        """The generated base profile holds on a system built from it: the generator and
        the checker agree on setting names and value formats."""
        settings = json.loads((PROFILES / "base.json").read_text())["settings"]
        self.system.config([f"{name}={s['value']}" for name, s in settings["kconfig"].items()])
        for name, s in settings["sysctl"].items():
            self.system.sysctl(name, s["value"])
        code, text = run(self.system.root, PROFILES)
        self.assertEqual(code, 0, text)
        self.assertIn("base: 25/25 settings hold", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v`

Expected: FAIL. The `test_check` module errors with `FileNotFoundError: [Errno 2] No such file or directory: '.../SOURCES/usr/bin/athanor-profile-check'`, and the 13 tests of Task 1 and 2 still pass.

- [ ] **Step 3: Write the checker**

Create `forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check`:

```python
#!/usr/bin/python3
"""Checks the running system against the kernel profile of its role combination.

Usage: athanor-profile-check [--root DIR] [--profiles DIR] [--quiet]

The role combination comes from the athanor.role= parameters on /proc/cmdline; its
effective profile is /usr/share/athanor/kernel-profile/<combination>.json, generated from
profile.toml (docs/architecture/doc_kernel_profile.md, sections 3, 7 and 12). Block P1
checks the kernel configuration (/proc/config.gz), sysctls (/proc/sys) and the runtime
state under /sys/kernel/security. Exit status: 0 when every setting holds, 1 on drift, 2
when the profile cannot be read.
"""

import argparse
import gzip
import json
import pathlib
import re
import sys
import zlib

PROFILES = pathlib.Path("/usr/share/athanor/kernel-profile")
SCHEMA = 1
KINDS = ("kconfig", "sysctl", "runtime")
ROLE_PATTERN = re.compile(r"^[a-z0-9-]+$")


def active_roles(root: pathlib.Path) -> list:
    """The athanor.role= values on /proc/cmdline, validated: a role name is lowercase
    letters, digits and hyphens, and never the reserved combination name "base"."""
    arguments = (root / "proc" / "cmdline").read_text().split()
    roles = sorted({arg.split("=", 1)[1] for arg in arguments if arg.startswith("athanor.role=")})
    for role in roles:
        if role == "base" or not ROLE_PATTERN.match(role):
            raise ValueError(f"invalid role {role!r} on /proc/cmdline")
    return roles


def validate(document) -> dict:
    """The settings table of a loaded profile document, or raise ValueError: a setting
    the checker cannot read must never be silently skipped and counted as holding."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    settings = document.get("settings")
    if not isinstance(settings, dict) or not settings:
        raise ValueError("settings must be a non-empty object")
    for kind, table in settings.items():
        if kind not in KINDS:
            raise ValueError(f"unknown setting kind {kind!r}, expected one of {', '.join(KINDS)}")
        if not isinstance(table, dict):
            raise ValueError(f"settings.{kind} must be an object")
        for name, entry in table.items():
            if not isinstance(entry, dict) or "value" not in entry:
                raise ValueError(f"settings.{kind}.{name} must be an object with a value")
    return settings


def combination_name(roles: list) -> str:
    return "+".join(roles) if roles else "base"


def kernel_config(root: pathlib.Path) -> dict:
    """{CONFIG_X: value} from /proc/config.gz; an option that is not set reads as n."""
    values = {}
    with gzip.open(root / "proc" / "config.gz", "rt") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("CONFIG_") and "=" in line:
                name, value = line.split("=", 1)
                values[name] = value
            elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
                values[line[2 : -len(" is not set")]] = "n"
    return values


def sysctl(root: pathlib.Path, name: str):
    path = root / "proc" / "sys" / name.replace(".", "/")
    try:
        return path.read_text().strip()
    except OSError:
        return None


def lockdown(root: pathlib.Path):
    text = (root / "sys" / "kernel" / "security" / "lockdown").read_text()
    for word in text.split():
        if word.startswith("[") and word.endswith("]"):
            return word[1:-1]
    return None


def lsm(root: pathlib.Path) -> list:
    return (root / "sys" / "kernel" / "security" / "lsm").read_text().strip().split(",")


RUNTIME = {"lockdown": lockdown, "lsm": lsm}


def compare(root: pathlib.Path, settings: dict) -> list:
    """[(key, expected, found)] for every setting that does not hold."""
    drift = []
    config = kernel_config(root) if settings.get("kconfig") else {}
    for name, setting in sorted(settings.get("kconfig", {}).items()):
        found = config.get(name, "n")
        if found != setting["value"]:
            drift.append((f"kconfig.{name}", setting["value"], found))
    for name, setting in sorted(settings.get("sysctl", {}).items()):
        found = sysctl(root, name)
        if found != str(setting["value"]):
            drift.append((f"sysctl.{name}", setting["value"], found))
    for name, setting in sorted(settings.get("runtime", {}).items()):
        expected = setting["value"]
        reader = RUNTIME.get(name)
        if reader is None:
            drift.append((f"runtime.{name}", expected, "no reader for this setting"))
            continue
        try:
            found = reader(root)
        except OSError as error:
            drift.append((f"runtime.{name}", expected, f"unreadable: {error.strerror}"))
            continue
        if isinstance(expected, list):
            holds = isinstance(found, list) and set(expected) <= set(found)
        else:
            holds = found == expected
        if not holds:
            drift.append((f"runtime.{name}", expected, found))
    return drift


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("/"))
    parser.add_argument("--profiles", type=pathlib.Path, default=PROFILES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        name = combination_name(active_roles(args.root))
        path = args.profiles / f"{name}.json"
        if not path.is_file():
            raise ValueError(f"role combination {name!r} has no profile (it is unknown or rejected)")
        settings = validate(json.loads(path.read_text()))
        drift = compare(args.root, settings)
        total = sum(len(entries) for entries in settings.values())
    except (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError, zlib.error) as error:
        print(f"athanor-profile-check: cannot check the profile: {error}", file=sys.stderr)
        return 2

    if not args.quiet:
        for key, expected, found in drift:
            print(f"DRIFT {key}: expected {expected!r}, found {found!r}")
        print(f"athanor-profile-check: {name}: {total - len(drift)}/{total} settings hold")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `chmod 0755 forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v`

Expected: `Ran 21 tests` … `OK`.

- [ ] **Step 5: Check the maintainer's running system**

Run: `python3 -B forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check --profiles forge/specs/athanor-kernel-profile/SOURCES/usr/share/athanor/kernel-profile`

Expected: `athanor-profile-check: base: 25/25 settings hold` with exit status 0. The P1 manifest was written from this machine's own values. A `DRIFT` line means the manifest in Task 2 does not match the image, and is fixed there rather than here.

- [ ] **Step 6: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/athanor-kernel-profile/SOURCES/usr/bin/athanor-profile-check forge/specs/athanor-kernel-profile/tests/test_check.py
git -C /var/home/hr-mes/athanor commit -m "feat(kernel-profile): check the running system against its effective profile" -m "athanor-profile-check reads the profile of the role combination on /proc/cmdline and compares it with /proc/config.gz, /proc/sys and /sys/kernel/security, reporting each drift."
```

---

### Task 4: The package and its place in the DAG

**Files:**
- Create: `forge/specs/athanor-kernel-profile/athanor-kernel-profile.spec`
- Modify: `forge/config/packages.json` (the `custom_packages` and `custom_tier1` arrays)

**Interfaces:**
- Consumes: `SOURCES/usr/bin/athanor-profile-check` (Task 3) and `SOURCES/usr/share/athanor/kernel-profile/*.json` (Task 2).
- Produces: the RPM `athanor-kernel-profile-1.0.0-1.fc43.noarch`, installing `/usr/bin/athanor-profile-check` and `/usr/share/athanor/kernel-profile/*.json`. Task 5 and Task 6 rely on the installed paths.

- [ ] **Step 1: Write the spec**

Create `forge/specs/athanor-kernel-profile/athanor-kernel-profile.spec`. It has no `Source:` lines, so `call-dag-compile.yml` builds it with `--build-in-place` after copying `SOURCES/` into `%{_sourcedir}`:

```spec
%global debug_package %{nil}
Name:           athanor-kernel-profile
Version:        1.0.0
Release:        1%{?dist}
Summary:        Athanor kernel profile: effective settings per role combination and their checker

License:        MIT
URL:            https://github.com/hr-mes/athanor
BuildArch:      noarch
Requires:       python3 >= 3.11

%description
The effective kernel profile of every allowed role combination, generated from
profile.toml (docs/architecture/doc_kernel_profile.md), and athanor-profile-check, which
compares the running system with the profile of its role combination.

%prep
# Nothing to unpack: the installed files come from SOURCES.

%build
# Nothing to build: kernel_profile.py generates the profiles in the repository.

%install
install -D -m 0755 %{_sourcedir}/usr/bin/athanor-profile-check %{buildroot}%{_bindir}/athanor-profile-check
install -d %{buildroot}%{_datadir}/athanor/kernel-profile
install -m 0644 %{_sourcedir}/usr/share/athanor/kernel-profile/*.json %{buildroot}%{_datadir}/athanor/kernel-profile/

%files
%{_bindir}/athanor-profile-check
%dir %{_datadir}/athanor
%dir %{_datadir}/athanor/kernel-profile
%{_datadir}/athanor/kernel-profile/*.json

%changelog
* Mon Sep 14 2026 Athanor Forge <forge@athanor.os> - 1.0.0-1
- Block P1 of the kernel profile: manifest, generated profiles and checker
```

- [ ] **Step 2: Register the package**

In `forge/config/packages.json`, add `"kernel-profile"` in two places:
- in `custom_packages`, on the line after `"system-tweaks",`;
- in `custom_tier1`, on the line after `"system-tweaks",`.

Keep the same indentation. The DAG maps the name `kernel-profile` to `forge/specs/athanor-kernel-profile`, and the system image installs every package of the tier 1 repository.

Run: `python3 -B -c 'import json; d=json.load(open("forge/config/packages.json")); assert "kernel-profile" in d["custom_packages"] and "kernel-profile" in d["custom_tier1"]; print("registered")'`

Expected: `registered`

- [ ] **Step 3: Build the RPM locally**

Run:

```bash
podman run --rm --security-opt label=disable -v /var/home/hr-mes/athanor:/workspace -w /workspace registry.fedoraproject.org/fedora:43 bash -c 'set -euo pipefail; dnf -y -q install rpm-build >/dev/null; mkdir -p /root/rpmbuild/SOURCES; cp -a forge/specs/athanor-kernel-profile/SOURCES/. /root/rpmbuild/SOURCES/; rpmbuild -bb --nodeps --build-in-place forge/specs/athanor-kernel-profile/athanor-kernel-profile.spec >/dev/null; rpm -qlp /root/rpmbuild/RPMS/noarch/athanor-kernel-profile-*.rpm; rpm -qp --requires /root/rpmbuild/RPMS/noarch/athanor-kernel-profile-*.rpm | grep python3'
```

Expected:
```
/usr/bin/athanor-profile-check
/usr/share/athanor
/usr/share/athanor/kernel-profile
/usr/share/athanor/kernel-profile/base.json
/usr/share/athanor/kernel-profile/desktop+laptop.json
/usr/share/athanor/kernel-profile/desktop.json
/usr/share/athanor/kernel-profile/laptop.json
/usr/share/athanor/kernel-profile/mesh.json
python3 >= 3.11
```

- [ ] **Step 4: Run the project verifier on the new files**

Run: `python3 -B scripts/verify.py specs shipped docs 2>&1 | grep -E 'kernel-profile|kernel_profile' ; test ${PIPESTATUS[1]} -eq 1 && echo "no findings for the new package"`

Expected: `no findings for the new package`. That means `grep` found no line naming the package. Findings from before this plan may still appear in the verifier's own output; they are not in scope.

- [ ] **Step 5: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/athanor-kernel-profile/athanor-kernel-profile.spec forge/config/packages.json
git -C /var/home/hr-mes/athanor commit -m "feat(kernel-profile): package the profiles and the checker in tier 1" -m "athanor-kernel-profile installs /usr/bin/athanor-profile-check and the generated profiles under /usr/share/athanor/kernel-profile."
```

---

### Task 5: Merge and verify the image carries the package

**Files:** none changed; this task ships Tasks 1–4.

**Interfaces:**
- Consumes: the commits of Tasks 1–4 on branch `kernel-profile-p1`.
- Produces: a published `athanor-system` image and ISO that contain `athanor-kernel-profile`. Task 6 waits for them, because every push to `forge/test/iso/**` runs acceptance against the newest ISO.

- [ ] **Step 1: Run the whole test suite once more**

Run: `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v && python3 -B forge/specs/athanor-kernel-profile/kernel_profile.py check`

Expected: `Ran 21 tests` … `OK`, then `kernel_profile: 5 combinations valid, generated files up to date`.

- [ ] **Step 2: Push and open the pull request**

Run: `gh run list --repo hr-mes/athanor --workflow athanor-forge-orchestrator.yml --status in_progress --json databaseId --jq length`

Expected: `0`. Do not push `forge/**` while an Orchestrator cycle runs; if the output is not `0`, wait until that run ends.

```bash
git -C /var/home/hr-mes/athanor push -u origin kernel-profile-p1
gh pr create --repo hr-mes/athanor --base iso-v0 --head kernel-profile-p1 --title "feat(kernel-profile): block P1, profile manifest, validator and checker" --body "$(cat <<'EOF'
## Summary

Block P1 of the kernel and platform profile (docs/architecture/doc_kernel_profile.md, section 15): a new tier 1 package, `athanor-kernel-profile`.

- `profile.toml`: typed manifest of the settings already in force (20 kernel options, 3 sysctls, lockdown level and active LSMs), the desktop, laptop and mesh roles, the `interactive` fragment and the rejected interactive plus mesh combinations.
- `kernel_profile.py`: composes every role combination with the rules of section 7 (lists by union, maps recursively, scalar conflicts only by priority or declared ordering, locked base settings) and generates one effective profile per allowed combination.
- `athanor-profile-check`: compares the running system with the profile of its role combination.
- CI: the lint workflow runs the validator and the unit tests.

The acceptance marker `profile-ok` follows in a separate pull request, once an ISO containing this package is published.

## Test plan

- [x] `python3 -B -m unittest discover -s forge/specs/athanor-kernel-profile/tests -v` (21 tests)
- [x] `kernel_profile.py check`: 5 combinations valid, generated files up to date
- [x] Local RPM build installs the checker and five profiles
- [x] `athanor-profile-check` on the maintainer's machine: base 25/25 settings hold
- [ ] Orchestrator builds the system image with the package

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge**

Run: `gh pr checks kernel-profile-p1 --repo hr-mes/athanor`

Expected: every reported check passes. `iso-v0` requires the `Kernel gate` check, and this pull request does not touch `forge/specs/azoth`, so that check never runs. Merge only with the maintainer's explicit consent, using `gh pr merge kernel-profile-p1 --repo hr-mes/athanor --rebase --admin`, as for pull request #27.

- [ ] **Step 4: Wait for the image and approve its signing**

Run: `gh run list --repo hr-mes/athanor --workflow athanor-forge-orchestrator.yml --branch iso-v0 --limit 1 --json databaseId,headSha,status --jq '.[0]'`

Expected: a run whose `headSha` is the merge commit. The `signing` environment requires the maintainer's approval (D43): the system image job waits on the run page until the maintainer approves it under "Review deployments". Then watch the run:

Run: `gh run watch <databaseId> --repo hr-mes/athanor --exit-status`

Expected: exit status 0.

- [ ] **Step 5: Verify the published image carries the package**

Run: `podman pull -q ghcr.io/hr-mes/athanor-system:latest >/dev/null && podman run --rm ghcr.io/hr-mes/athanor-system:latest rpm -q athanor-kernel-profile && podman run --rm ghcr.io/hr-mes/athanor-system:latest ls /usr/share/athanor/kernel-profile`

Expected:
```
athanor-kernel-profile-1.0.0-1.fc43.noarch
base.json
desktop+laptop.json
desktop.json
laptop.json
mesh.json
```

---

### Task 6: The `profile-ok` acceptance marker and the P1 gate

**Files:**
- Modify: `forge/test/iso/console.py`, in three places: the `MARKERS` tuple, a new `PROFILE_PROBE` constant after `GREETER_PROBE_WAIT`, and `ask_about_the_greeter`.
- Modify: `forge/test/iso/verdict.py`, in three places: the module docstring, a new `PROFILE_SIGNALS` constant, and `main`.
- Modify: `forge/test/iso/test_verdict.py`, in five places: `test_pass`, a new `test_profile_drift_fails`, a new `test_profile_unreadable_fails`, `test_console_logs_in_opens_settings_and_stops`, and the `main` list.
- Modify: `NEXT.md`, adding a new section before `## Dopo`.

**Interfaces:**
- Consumes: `athanor-profile-check --quiet` on the installed guest (Task 4 and Task 5).
- Produces:
  - Guest markers `PROFILE_OK`, `PROFILE_DRIFT` and `PROFILE_UNREADABLE`, recorded as phases `profile-ok`, `profile-drift` and `profile-unreadable` — the checker's own exit codes 0, 1 and 2 (docs/architecture/doc_kernel_profile.md, section 12 item 3).
  - A new phase `profile-asked`.
  - A verdict that fails without `profile-ok`, with report line `- kernel profile holds: <phase or NO>`.

- [ ] **Step 1: Write the failing tests**

In `forge/test/iso/test_verdict.py`, make four changes.

First, in `test_pass`, add `("profile-ok", 390),` to the phase list after `("kickstart-done", 110),` and add this assertion after `assert "**PASS**" in report, report`:

```python
    assert "kernel profile holds: profile-ok" in report, report
```

Second, add these two tests after `test_session_without_settings_fails`:

```python
def test_profile_drift_fails(tmp: pathlib.Path) -> None:
    """A desktop that works on a kernel profile that does not hold is not a pass: the
    installed system is not the one the profile describes."""
    code, report = verdict(
        tmp,
        [
            ("installed", 100),
            ("kickstart-done", 110),
            ("profile-drift", 390),
            ("greeter-alive", 400),
            ("session-alive", 460),
            ("settings-alive", 500),
        ],
    )
    assert code != 0, "a run whose kernel profile drifted passed"
    assert "**FAIL**" in report, report
    assert "kernel profile holds: NO" in report, report


def test_profile_unreadable_fails(tmp: pathlib.Path) -> None:
    """A desktop that works when the kernel profile itself could not be read is not a
    pass either: an unreadable profile proves nothing about the installed system."""
    code, report = verdict(
        tmp,
        [
            ("installed", 100),
            ("kickstart-done", 110),
            ("profile-unreadable", 390),
            ("greeter-alive", 400),
            ("session-alive", 460),
            ("settings-alive", 500),
        ],
    )
    assert code != 0, "a run whose kernel profile could not be read passed"
    assert "**FAIL**" in report, report
    assert "kernel profile holds: NO" in report, report
```

Third, in `test_console_logs_in_opens_settings_and_stops`, replace these two lines:

```python
        conn.sendall(b"athanor login: ")
        typed_until(conn, b"GREETER_%s", 20)
```

with:

```python
        conn.sendall(b"athanor login: ")
        typed = typed_until(conn, b"PROFILE_%s", 20)
        conn.sendall(b"PROFILE_OK\r\n")
        if b"GREETER_%s" not in typed:
            typed_until(conn, b"GREETER_%s", 20)
```

In the same test, add `"profile-ok",` as the first entry of the `for expected in (` tuple.

Fourth, in `main`, add `test_profile_drift_fails,` and `test_profile_unreadable_fails,` after `test_session_without_settings_fails,`.

Run: `python3 -B forge/test/iso/test_verdict.py`

Expected: FAIL with `AssertionError`, raised either on `kernel profile holds: profile-ok` in `test_pass` or, when run in list order, on `test_profile_drift_fails` or `test_profile_unreadable_fails` passing a run that should not.

- [ ] **Step 2: Add the probe to console.py**

In `forge/test/iso/console.py`, insert these three entries into `MARKERS` right after `(b"Started greetd.service", "greeter-unit"),`:

```python
    # The guest's own answer to PROFILE_PROBE below: athanor-profile-check found the
    # installed system's kernel profile holding, reported what drifted, or could not
    # read or validate the profile at all.
    (b"PROFILE_OK", "profile-ok"),
    (b"PROFILE_DRIFT", "profile-drift"),
    (b"PROFILE_UNREADABLE", "profile-unreadable"),
```

Insert this after the line `GREETER_PROBE_WAIT = 50.0`:

```python

# Ask the guest whether its kernel profile holds (docs/architecture/doc_kernel_profile.md,
# section 12 item 3). athanor-profile-check's own exit status tells the three cases apart:
# 0 the profile holds, 1 drift, anything else the profile itself could not be read or
# validated. On drift or on an unreadable profile it runs a second time without --quiet,
# so its report lands in the console log next to the answer. As with the other probes,
# printf assembles the marker, so the echo of the typed line cannot pass for the answer.
PROFILE_PROBE = (
    b"athanor-profile-check --quiet; case $? in"
    b" 0) printf 'PROFILE_%s\\n' OK;;"
    b" 1) printf 'PROFILE_%s\\n' DRIFT; athanor-profile-check;;"
    b" *) printf 'PROFILE_%s\\n' UNREADABLE; athanor-profile-check;;"
    b" esac"
)
# A handful of file reads, and a margin for the report on drift or on an unreadable profile.
PROFILE_PROBE_WAIT = 10.0
```

In `ask_about_the_greeter`, replace:

```python
        s.sendall(GUEST_PASSWORD + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE * PACE)
        ask(GREETER_PROBE, GREETER_PROBE_WAIT)
```

with:

```python
        s.sendall(GUEST_PASSWORD + b"\n")
        time.sleep(DIAGNOSTIC_PAUSE * PACE)
        ask(PROFILE_PROBE, PROFILE_PROBE_WAIT)
        note("profile-asked")
        ask(GREETER_PROBE, GREETER_PROBE_WAIT)
```

- [ ] **Step 3: Require the marker in verdict.py**

In `forge/test/iso/verdict.py`, replace `Five things have to be true for a pass,` with `Six things have to be true for a pass,` in the module docstring. Then insert this line after `  kickstart-done   our additions ran too, so the disk has an account on it`:

```text
  profile          athanor-profile-check reports the installed system's kernel profile holds
                   (fails on drift, and fails if the profile itself could not be read)
```

After the `SETTINGS_SIGNALS = ("settings-alive",)` line, insert:

```python
# And the kernel profile: PROFILE_OK is the guest's report that athanor-profile-check found
# every setting of its role combination's profile in force (doc_kernel_profile.md,
# section 12 item 3). PROFILE_DRIFT fails the run by leaving this unset.
PROFILE_SIGNALS = ("profile-ok",)
```

In `main`, add after `kickstart_done = "kickstart-done" in phases`:

```python
    profile = next((s for s in PROFILE_SIGNALS if s in phases), None)
```

Add this right after the three-line `lines.append(` call that writes `unattended kickstart finished`:

```python
    lines.append(f"- kernel profile holds: {profile if profile else 'NO'}")
```

Finally, in the `ok = (` expression, add `and profile is not None` after `and kickstart_done`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -B forge/test/iso/test_verdict.py`

Expected: every test prints `ok`, including `ok  test_profile_drift_fails`, `ok  test_profile_unreadable_fails` and `ok  test_console_logs_in_opens_settings_and_stops`, followed by `all checks passed`.

- [ ] **Step 5: Record block group P in NEXT.md**

In `NEXT.md`, insert this before the line `## Dopo`:

```markdown
## BLOCCO P — kernel and platform profile

Specification: [docs/architecture/doc_kernel_profile.md](docs/architecture/doc_kernel_profile.md), approved at gate P0 on 2026-09-14. Blocks run in order behind their gates (section 15); spike S1 runs alongside P1–P4a.

- **P1**: `forge/specs/athanor-kernel-profile`, holding `profile.toml`, `kernel_profile.py` (validator over every role combination and generator of the effective profiles), `athanor-profile-check` and the acceptance marker `profile-ok`. Plan: [docs/superpowers/plans/2026-09-14-kernel-profile-p1.md](docs/superpowers/plans/2026-09-14-kernel-profile-p1.md). Gate: ISO acceptance PASS with `profile-ok`.
- **P2**: kernel build profile (section 5) and boot matrix assertions. Gate: Kernel Build gate green.

```

Run: `python3 -B scripts/verify.py docs 2>&1 | grep -F 'NEXT.md' ; test ${PIPESTATUS[1]} -eq 1 && echo "NEXT.md links resolve"`

Expected: `NEXT.md links resolve`

- [ ] **Step 6: Confirm the newest ISO carries the package, then commit and push**

Run: `gh run list --repo hr-mes/athanor --workflow athanor-forge-orchestrator.yml --branch iso-v0 --status success --limit 1 --json databaseId,headSha,createdAt --jq '.[0]'`

Expected: the run of Task 5 Step 4, or a later one. Acceptance installs the newest published ISO. Pushing this commit starts it at once, so push only after Task 5 Step 5 has passed.

```bash
git -C /var/home/hr-mes/athanor add forge/test/iso/console.py forge/test/iso/verdict.py forge/test/iso/test_verdict.py NEXT.md
git -C /var/home/hr-mes/athanor commit -m "test(iso): require the kernel profile to hold on the installed system" -m "Acceptance asks the guest to run athanor-profile-check and fails the run without its PROFILE_OK answer; NEXT.md records block group P."
git -C /var/home/hr-mes/athanor push origin kernel-profile-p1
gh pr create --repo hr-mes/athanor --base iso-v0 --head kernel-profile-p1 --title "test(iso): require profile-ok in ISO acceptance" --body "$(cat <<'EOF'
## Summary

Gate of block P1 (docs/architecture/doc_kernel_profile.md, section 15): ISO acceptance asks the installed guest to run `athanor-profile-check` and requires its `PROFILE_OK` answer. On drift, the checker's report is written to the console log. NEXT.md gains block group P.

## Test plan

- [x] `python3 -B forge/test/iso/test_verdict.py` (includes `test_profile_drift_fails`)
- [x] The published system image contains `athanor-kernel-profile`
- [ ] ISO acceptance on push to iso-v0: PASS with `kernel profile holds: profile-ok`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If pull request 1 of Task 5 was merged with `--rebase`, create this second pull request from a branch rebased on the updated `iso-v0` (`git -C /var/home/hr-mes/athanor rebase origin/iso-v0` after `git -C /var/home/hr-mes/athanor fetch origin iso-v0`), so that it carries only the Task 6 commit.

- [ ] **Step 7: Merge and pass the P1 gate**

Merge with the maintainer's consent, as in Task 5 Step 3. The push to `iso-v0` touches `forge/test/iso/**`, which starts the `ISO Acceptance` workflow.

Run: `gh run list --repo hr-mes/athanor --workflow iso-acceptance.yml --branch iso-v0 --limit 1 --json databaseId,status --jq '.[0]'`, then `gh run watch <databaseId> --repo hr-mes/athanor --exit-status`

Expected: exit status 0. The run summary shows `**PASS**` and `- kernel profile holds: profile-ok`. That is the P1 gate.

---

## Self-Review

1. **Spec coverage.** The P1 row of section 15 has four parts, all covered:
   - manifest: Task 2;
   - validator over every role combination, covering the composition rules of section 7: Task 1;
   - checker covering settings already in force: Task 3;
   - acceptance with `profile-ok`: Task 6.

   The rule rejecting interactive plus mesh (section 7) is in Task 2. Role selection through `athanor.role=` is in Task 3. The generated effective profiles checked in CI match section 3, and the CI part of section 12 item 1 is in Task 2. The later parts of item 4 (command line, `scx_loader`, integrity mode, PCR 12, gating `boot-complete.target`) are out of P1, as the Global Constraints state.
2. **Placeholder scan.** Every code step contains its code, every command states its expected output, and no step refers to an undefined function.
3. **Type consistency.** The names match across tasks:
   - `kernel_profile.main`, `build`, `combinations`, `effective`, `render`, `combination_name` and `ProfileError` are defined in Task 1 and used in Task 1 and 2.
   - The JSON keys `schema`, `combination`, `roles` and `settings.<kind>.<name>.value|decision` are written in Task 1 and read in Task 3.
   - `athanor-profile-check` has the options `--root`, `--profiles` and `--quiet`, and the output line `<combination>: <held>/<total> settings hold`. Task 3 defines them, and the Task 3, 5 and 6 tests and commands use them.
   - The phase names `profile-ok`, `profile-drift` and `profile-asked` agree between `console.py`, `verdict.py` and `test_verdict.py`.
