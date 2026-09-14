# Kernel Patch Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "third-party kernel patches apply without fuzz" a permanent, workable rule. When an upstream CachyOS patch stops applying, it is refreshed once, reviewed by a human and committed. The bump bot never auto-merges such a bump. The first use of the mechanism unblocks the 7.1.8 → 7.2.5 bump (PR #29).

**Architecture:**
- **Strict application:** `build.sh` keeps applying `patches.list` with `git apply` and no fuzz.
- **Refreshed copies:** a new directory, `patches/refreshed/`, holds refreshed copies. Each copy has a preamble that records the SHA-256 of the upstream file it derives from. `prep` and `build` refuse a copy that is missing, stale or obsolete.
- **Refresh stage:** a new `--stage refresh` rebuilds the real merged tree. GNU `patch --fuzz=2` proposes each copy that is needed; the stage verifies that the copy applies strictly to both trees, then writes it to `--out` together with the GNU patch report.
- **BuildRequires later:** `dnf builddep` moves after the patch step. A patch failure then stops `prep` in seconds, and `refresh` needs no toolchain.
- **Bump bot:** `kernel-bump.yml` recognises the `refresh needed` failure and opens that PR without auto-merge.

**Tech Stack:** Bash (`build.sh`, run inside `forge/specs/azoth/builder/Containerfile`, which already ships `patch`), git plumbing, GNU patch 2.8, GitHub Actions YAML, Italian architecture documentation.

**Spec:** `docs/architecture/doc_kernel_build.md`: section 1 (principles), 2 (files), 3 (build), 8 (bump bot) and 13 (maintainer decisions). The design was approved by the maintainer on 2026-09-14 as a permanent decision. The decision is:

> The build applies third-party patches strictly with git apply, no fuzz. When an upstream patch no longer applies, a repository script refreshes it once: it rebuilds the real merged tree, applies the upstream patch with GNU patch as a candidate generator, reports the fuzzed hunks, and writes a refreshed patch that a human reviews and commits, tied to the upstream commit and file hash it derives from. The build then applies the refreshed copy strictly; if the upstream patch changes, the refreshed copy is stale and the build stops asking for a new refresh. The bump bot distinguishes: strict apply ⇒ auto-merge as today; refresh needed ⇒ clearly labelled PR, never auto-merged.

## Global Constraints

- **Section 1.3 of the spec:** "Una patch che non si applica fa fallire la build (`git apply` è senza fuzz), non viene "saltata"." Fuzz is allowed only inside `--stage refresh`, as a proposal, and never in `prep`, `microvm` or `build`.
- **Section 1.4 of the spec:** "I gate falliscono forte … con il messaggio esatto. Nessun `|| true`."
- **Section 1.2 of the spec:** "Nessuna risoluzione "dinamica" a build time: la scelta della versione avviene in una PR, mai nel job di build." A refreshed copy is a reviewed, committed file, never generated during a build.
- **Project rules (CLAUDE.md):**
  - English for code comments, commit messages and PR text. `doc_kernel_build.md` and `KERNEL.md` are written in Italian, so edits to them stay in Italian.
  - Logic lives in repository scripts; workflow `run:` blocks stay short.
  - No `|| true`, no `continue-on-error`.
  - Never prefix commands with `cd`.
  - Scratch output goes to the session scratchpad: `/tmp/claude-1000/-var-home-hr-mes-athanor/a017eddd-482c-4c5e-9fdb-3bfc898b9a39/scratchpad`, written `$SCRATCH` below.
- **Branch:** all work goes on `bump/kernel-20260914-1919`, the branch of PR #29, checked out locally from `origin/bump/kernel-20260914-1919`. Its pins are already 7.2.5: `FEDORA_KERNEL_NVR=7.2.5-100.fc43`, `CACHYOS_RELEASE=cachyos-7.2.5-1`, `CACHYOS_PATCHES_COMMIT=9bf8104a95f8c0c60193fd65be3f11bc1fa05f57`.
- **Commit trailers:** every commit ends with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4`
- **Outward steps need the maintainer's consent:** pushing, editing PR #29, merging and approving signing jobs.

## Local builder invocation (used by Tasks 1 and 4)

The CI prep job runs `build.sh` in `localhost/azoth-builder`, with the repository at `/forge` and a persistent cache at `/var/cache/azoth`. Locally:

```bash
podman build -t localhost/azoth-builder /var/home/hr-mes/athanor/forge/specs/azoth/builder
mkdir -p "$HOME/.cache/azoth" "$SCRATCH/azoth-out"
builder() {
  podman run --rm --security-opt label=disable \
    -v /var/home/hr-mes/athanor:/forge \
    -v "$HOME/.cache/azoth:/var/cache/azoth" \
    -v "$SCRATCH/azoth-out:/out" \
    -w /forge localhost/azoth-builder "$@"
}
```

The first run downloads about 600 MB of pinned sources into `$HOME/.cache/azoth`; later runs reuse them.

## File Structure

| Path | Responsibility |
| --- | --- |
| `forge/specs/azoth/build.sh` | Resolution of each `patches.list` entry to its upstream file or refreshed copy, with strict application; the `refresh` stage; `builddep` moved after the patches |
| `forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch` | The reviewed refreshed BORE patch for 7.2.5 (Task 4) |
| `.github/workflows/kernel-bump.yml` | Prep outcome `REFRESH`, and the PR opened without auto-merge in that case |
| `docs/architecture/doc_kernel_build.md` | The permanent rule and the refresh flow (sections 1, 2, 3, 8, 13) |
| `forge/specs/azoth/KERNEL.md` | Directory table: `patches/refreshed/` and the `refresh` stage |

`build-inputs.py` needs no change: it already hashes every `patches/**/*.patch` (`rglob`), so a refreshed copy changes the build inputs. The Athanor patch loop uses `find "$HERE/patches" -maxdepth 1`, so it does not pick up `patches/refreshed/`.

---

### Task 1: build.sh — strict resolution and the refresh stage

**Files:**
- Modify: `forge/specs/azoth/build.sh`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `build.sh --stage refresh --out DIR` writes `DIR/refreshed/<patches.list path>` for every patch that needs a refresh, and exits 0 after the patch step.
  - On a patch that does not apply, `prep`, `microvm` and `build` fail with a stderr line starting exactly with `build.sh: refresh needed: <patches.list path> (`. Task 2 greps for `^build.sh: refresh needed: `.
  - A refreshed copy starts with three preamble lines, then a blank line, the indented GNU patch report, a blank line and a `git diff --binary`:

    ```
    Refreshed-From: CachyOS/kernel-patches <CACHYOS_PATCHES_COMMIT> <SERIES>/<path>
    Upstream-SHA256: <sha256 of the upstream file>
    Refreshed-On: <CACHYOS_RELEASE> merged with the Red Hat patch of kernel-<FEDORA_KERNEL_NVR>
    ```

  - The obsolete-copy failure message starts with `build.sh: patches/refreshed/<path> is obsolete`.

- [ ] **Step 1: Record the failing behaviour (RED)**

The current `build.sh` on this branch fails prep with a raw git error and no hint about what to do. The evidence is in the body of PR #29:

Run: `gh pr view 29 --repo hr-mes/athanor --json body --jq .body | grep -E "^## prep|patch failed|does not apply"`

Expected:
```
## prep: FAIL
error: patch failed: include/linux/sched.h:824
error: include/linux/sched.h: patch does not apply
```

- [ ] **Step 2: Make `--out` absolute and accept the refresh stage**

In `forge/specs/azoth/build.sh`, replace:

```bash
usage() { echo "usage: ${0##*/} --stage manifest|prep|microvm|build --out DIR [--variant NAME]" >&2; exit 2; }
```

with:

```bash
usage() { echo "usage: ${0##*/} --stage manifest|prep|refresh|microvm|build --out DIR [--variant NAME]" >&2; exit 2; }
```

Replace:

```bash
[[ ( $STAGE == manifest || $STAGE == prep || $STAGE == microvm || $STAGE == build ) && -n $OUT ]] || usage
```

with:

```bash
[[ ( $STAGE == manifest || $STAGE == prep || $STAGE == refresh || $STAGE == microvm || $STAGE == build ) && -n $OUT ]] || usage
```

Replace:

```bash
mkdir -p "$CACHE" "$OUT" "$TOP"
```

with:

```bash
mkdir -p "$CACHE" "$OUT" "$TOP"
OUT=$(cd "$OUT" && pwd)     # absolute: the patch step applies files from inside $WORK/b
```

In the header comment, replace:

```bash
# regenerates SOURCES/sources.sha256. The microvm stage runs prep and compiles only the
```

with:

```bash
# regenerates SOURCES/sources.sha256. The refresh stage stops after the patches and writes
# to DIR/refreshed the copies of the CachyOS patches that no longer apply without fuzz, for
# a human to review and commit under patches/refreshed (section 8). The microvm stage runs prep and compiles only the
```

- [ ] **Step 3: Move `dnf builddep` after the patch step**

Delete this block, which currently sits just before `# --- tree ---`:

```bash
# Before the config derivation: listnewconfig must see the same toolchain as rpmbuild
# (rust-src, bindgen, pahole), otherwise RUST_IS_AVAILABLE and the options depending on
# it change between the pre-pass and the Fedora gate.
step "BuildRequires of kernel.spec"
dnf -y builddep "${DEFINES[@]}" "$TOP/SPECS/kernel.spec"
```

Insert it immediately before the line `# --- config -------------------------------------------------------------------------`, with this comment:

```bash
# Before the config derivation: listnewconfig must see the same toolchain as rpmbuild
# (rust-src, bindgen, pahole), otherwise RUST_IS_AVAILABLE and the options depending on
# it change between the pre-pass and the Fedora gate. After the patches: a patch that does
# not apply stops prep in seconds, and the refresh stage, which ends there, needs no toolchain.
step "BuildRequires of kernel.spec"
dnf -y builddep "${DEFINES[@]}" "$TOP/SPECS/kernel.spec"

```

- [ ] **Step 4: Replace the `patches.list` loop**

Replace exactly:

```bash
for p in "${PATCHES[@]}"; do
  g apply --cached "$CACHE/$(patch_file "$p")"
  (cd "$WORK/b" && git apply "$CACHE/$(patch_file "$p")")     # the CachyOS tree serves the config derivation
done
```

with:

```bash
# patches/refreshed/ (doc_kernel_build.md, sections 1 and 8): a CachyOS patch that no
# longer applies without fuzz is refreshed once with --stage refresh, where GNU patch
# proposes a copy on the real merged tree and a human reviews the fuzzed hunks before
# committing it. The copy records the hash of the upstream file it comes from. prep and
# build apply everything with git apply, without fuzz, and stop when a copy is needed,
# stale (refreshed from another upstream file) or obsolete (the upstream file applies again).
REFRESHED=$HERE/patches/refreshed
sha256_of() { sha256sum "$1" | cut -d' ' -f1; }
recorded_sha256() { sed -n 's/^Upstream-SHA256: //p' "$1"; }
applies() { # applies PATCH: PATCH applies without fuzz to the merged index and to the CachyOS tree
  g apply --cached --check "$1" 2> /dev/null && (cd "$WORK/b" && git apply --check "$1" 2> /dev/null)
}
refresh_copy() { # refresh_copy PATH UPSTREAM: GNU patch proposes the refreshed copy; prints its path
  local p=$1 upstream=$2 dest=$OUT/refreshed/$1 tmp=$WORK/refresh idx=$WORK/refresh.index
  local log before after f mode files present
  mapfile -t files < <(git apply --numstat "$upstream" | cut -f3)
  [[ -z $(printf '%s\n' "${files[@]}" | awk '/ => /') ]] || die "$p: a patch with renames cannot be refreshed, refresh it by hand"
  rm -rf "$tmp" && mkdir -p "$tmp"
  mapfile -t present < <(g ls-files -- "${files[@]}")
  [[ ${#present[@]} -eq 0 ]] || g checkout-index --prefix="$tmp/" -- "${present[@]}"
  if ! log=$(patch -d "$tmp" -p1 --forward --fuzz=2 --no-backup-if-mismatch --reject-file=- < "$upstream" 2>&1); then
    printf '%s\n' "$log" >&2
    die "$p: GNU patch cannot apply it even with fuzz 2, refresh it by hand"
  fi
  # The copy is the diff between the index and the files GNU patch produced, written through
  # a second index so the real one moves only when the copy is applied below.
  before=$(g write-tree)
  cp "$WORK/a/.git/index" "$idx"
  for f in "${files[@]}"; do
    if [[ -f $tmp/$f ]]; then
      mode=100644
      [[ ! -x $tmp/$f ]] || mode=100755
      GIT_INDEX_FILE=$idx g update-index --add --cacheinfo "$mode,$(g hash-object -w "$tmp/$f"),$f"
    else
      GIT_INDEX_FILE=$idx g update-index --force-remove -- "$f"
    fi
  done
  after=$(GIT_INDEX_FILE=$idx g write-tree)
  mkdir -p "$(dirname "$dest")"
  {
    echo "Refreshed-From: CachyOS/kernel-patches $CACHYOS_PATCHES_COMMIT $SERIES/$p"
    echo "Upstream-SHA256: $(sha256_of "$upstream")"
    echo "Refreshed-On: $CACHYOS_RELEASE merged with the Red Hat patch of kernel-$FEDORA_KERNEL_NVR"
    echo
    echo "GNU patch output: review every hunk applied with fuzz before committing this copy."
    sed 's/^/  /' <<< "$log"
    echo
    g diff --binary "$before" "$after"
  } > "$dest"
  applies "$dest" || die "$p: the refreshed copy does not apply without fuzz to both trees, which need different copies: refresh it by hand"
  echo "$p: refreshed copy written to $dest" >&2
  echo "$dest"
}
for p in "${PATCHES[@]}"; do
  upstream=$CACHE/$(patch_file "$p")
  copy=$REFRESHED/$p
  if [[ $STAGE == refresh ]]; then
    if applies "$upstream"; then
      use=$upstream
      [[ ! -f $copy ]] || echo "$p: the upstream patch applies without fuzz, delete patches/refreshed/$p"
    elif [[ -f $copy && $(recorded_sha256 "$copy") == "$(sha256_of "$upstream")" ]] && applies "$copy"; then
      use=$copy
      echo "$p: patches/refreshed/$p is up to date"
    else
      use=$(refresh_copy "$p" "$upstream")
    fi
  elif [[ -f $copy ]]; then
    [[ $(recorded_sha256 "$copy") == "$(sha256_of "$upstream")" ]] \
      || die "refresh needed: $p (patches/refreshed/$p was refreshed from another upstream file)"
    ! applies "$upstream" || die "patches/refreshed/$p is obsolete: the upstream patch applies without fuzz again, delete the copy"
    applies "$copy" || die "refresh needed: $p (patches/refreshed/$p no longer applies without fuzz)"
    use=$copy
  else
    applies "$upstream" || die "refresh needed: $p (it no longer applies without fuzz)"
    use=$upstream
  fi
  g apply --cached "$use"
  (cd "$WORK/b" && git apply "$use")     # the CachyOS tree serves the config derivation
done
if [[ $STAGE == refresh ]]; then
  step "refresh done: the copies to review are in $OUT/refreshed (none if nothing needed a refresh)"
  exit 0
fi
```

- [ ] **Step 5: Lint**

Run: `bash -n forge/specs/azoth/build.sh && shellcheck -x forge/specs/azoth/build.sh`

Expected: no output and exit status 0. If shellcheck reports findings on lines this task did not change, compare with `git stash` to confirm they were already there, and report them without fixing them.

- [ ] **Step 6: prep now names the refresh (GREEN for the message)**

Using the builder from "Local builder invocation":

Run: `builder bash forge/specs/azoth/build.sh --stage prep --out /out 2>&1 | tail -3; echo "exit ${PIPESTATUS[0]}"`

Expected: the last lines include `build.sh: refresh needed: sched/0001-bore-cachy.patch (it no longer applies without fuzz)` and `exit 1`. The run must stop before `>>> BuildRequires of kernel.spec`: check with `builder bash forge/specs/azoth/build.sh --stage prep --out /out 2>&1 | grep -c "BuildRequires of kernel.spec"`, which prints `0`.

- [ ] **Step 7: refresh proposes the copy**

Run: `builder bash forge/specs/azoth/build.sh --stage refresh --out /out 2>&1 | tail -4; echo "exit ${PIPESTATUS[0]}"`

Expected: `sched/0001-bore-cachy.patch: refreshed copy written to /out/refreshed/sched/0001-bore-cachy.patch`, the `refresh done` step and `exit 0`.

Run: `head -12 "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch"`

Expected: the three preamble lines (`Refreshed-From: CachyOS/kernel-patches 9bf8104a95f8c0c60193fd65be3f11bc1fa05f57 7.2/sched/0001-bore-cachy.patch`, `Upstream-SHA256: …`, `Refreshed-On: cachyos-7.2.5-1 merged with the Red Hat patch of kernel-7.2.5-100.fc43`) and a GNU patch report containing `with fuzz`.

- [ ] **Step 8: a stale copy is refused**

Place the proposed copy in the repository with a wrong hash (it is not committed in this task):

```bash
mkdir -p forge/specs/azoth/patches/refreshed/sched
sed 's/^Upstream-SHA256: .*/Upstream-SHA256: 0000000000000000000000000000000000000000000000000000000000000000/' \
  "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch" > forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch
```

Run: `builder bash forge/specs/azoth/build.sh --stage prep --out /out 2>&1 | tail -1; echo "exit ${PIPESTATUS[0]}"`

Expected: `build.sh: refresh needed: sched/0001-bore-cachy.patch (patches/refreshed/sched/0001-bore-cachy.patch was refreshed from another upstream file)` and `exit 1`.

Then put the unmodified copy in place:

Run: `cp "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch" forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch && builder bash forge/specs/azoth/build.sh --stage refresh --out /out 2>&1 | grep "sched/0001-bore-cachy.patch:"`

Expected: `sched/0001-bore-cachy.patch: patches/refreshed/sched/0001-bore-cachy.patch is up to date`

Remove it again, since Task 4 commits it after the maintainer's review:

Run: `rm -r forge/specs/azoth/patches/refreshed && git -C /var/home/hr-mes/athanor status --short`

Expected: only ` M forge/specs/azoth/build.sh`.

- [ ] **Step 9: an obsolete copy is refused**

On the 7.1.8 pins the upstream BORE patch still applies without fuzz. Build a scratch worktree of `origin/iso-v0` with the new `build.sh` and a fake copy of the 7.1.8 upstream file:

```bash
git -C /var/home/hr-mes/athanor worktree add "$SCRATCH/azoth-iso" origin/iso-v0
cp /var/home/hr-mes/athanor/forge/specs/azoth/build.sh "$SCRATCH/azoth-iso/forge/specs/azoth/build.sh"
mkdir -p "$SCRATCH/azoth-iso/forge/specs/azoth/patches/refreshed/sched"
hash=$(awk '/-0001-bore-cachy.patch$/ {print $1}' "$SCRATCH/azoth-iso/forge/specs/azoth/SOURCES/sources.sha256")
printf 'Upstream-SHA256: %s\n' "$hash" > "$SCRATCH/azoth-iso/forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch"
podman run --rm --security-opt label=disable -v "$SCRATCH/azoth-iso:/forge" -v "$HOME/.cache/azoth:/var/cache/azoth" \
  -v "$SCRATCH/azoth-out:/out" -w /forge localhost/azoth-builder \
  bash forge/specs/azoth/build.sh --stage prep --out /out 2>&1 | tail -1
```

Expected: `build.sh: patches/refreshed/sched/0001-bore-cachy.patch is obsolete: the upstream patch applies without fuzz again, delete the copy`.

Clean up: `git -C /var/home/hr-mes/athanor worktree remove --force "$SCRATCH/azoth-iso"`

- [ ] **Step 10: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/azoth/build.sh
git -C /var/home/hr-mes/athanor commit -m "feat(kernel): refresh third-party patches instead of fuzzing them" -m "build.sh keeps applying patches.list with git apply and no fuzz. A patch that no longer applies stops prep with 'refresh needed'; --stage refresh rebuilds the merged tree, lets GNU patch propose a copy, verifies it applies strictly to both trees and writes it for review. Committed copies under patches/refreshed record the hash of their upstream file, so a stale or obsolete copy stops the build. dnf builddep now runs after the patches, so these failures are immediate." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 2: kernel-bump.yml — a refresh never auto-merges

**Files:**
- Modify: `.github/workflows/kernel-bump.yml`, in the `prep` job's "Prep (signatures, patches, config gate)" step and upload step, and in the `pr` job's "Branch, commit, PR with auto-merge" step.

**Interfaces:**
- Consumes: the stderr line `build.sh: refresh needed: <path> (<reason>)` from Task 1.
- Produces:
  - a file `prep-outcome` holding `ok`, `FAIL` or `REFRESH`, uploaded in the `bump-prep` artifact;
  - a PR whose title ends with ` (patch refresh needed)` and which gets no `gh pr merge --auto` when the outcome is `REFRESH`.

- [ ] **Step 1: Classify the prep outcome**

In the "Prep (signatures, patches, config gate)" step, replace:

```yaml
          outcome=ok
          if ! podman run --rm \
                 -v "$GITHUB_WORKSPACE:/forge" \
                 -v "$HOME/.cache/azoth:/var/cache/azoth" \
                 -w /forge localhost/azoth-builder \
                 bash forge/specs/azoth/build.sh --stage prep --out /forge/out > prep.log 2>&1; then
            outcome=FAIL
          fi
          {
            echo; echo "## prep: ${outcome}"; echo
            if [[ $outcome == FAIL ]]; then
              echo '```'; tail -n 40 prep.log; echo '```'
            fi
```

with:

```yaml
          outcome=ok
          if ! podman run --rm \
                 -v "$GITHUB_WORKSPACE:/forge" \
                 -v "$HOME/.cache/azoth:/var/cache/azoth" \
                 -w /forge localhost/azoth-builder \
                 bash forge/specs/azoth/build.sh --stage prep --out /forge/out > prep.log 2>&1; then
            outcome=FAIL
            if grep -q '^build.sh: refresh needed: ' prep.log; then outcome=REFRESH; fi
          fi
          echo "$outcome" > prep-outcome
          {
            echo; echo "## prep: ${outcome}"; echo
            if [[ $outcome == REFRESH ]]; then
              echo 'A CachyOS patch no longer applies without fuzz. On this branch run `build.sh --stage refresh`, review the hunks GNU patch applied with fuzz, commit the copy under `forge/specs/azoth/patches/refreshed/` and merge by hand (doc_kernel_build.md, section 8). This PR does not merge by itself.'
              echo; echo '```'; grep '^build.sh: refresh needed: ' prep.log; echo '```'
            fi
            if [[ $outcome == FAIL ]]; then
              echo '```'; tail -n 40 prep.log; echo '```'
            fi
```

In the following `actions/upload-artifact` step of the `prep` job (name `bump-prep`), add `prep-outcome` to `path`:

```yaml
          path: |
            prep.md
            prep.log
            prep-outcome
            forge/specs/azoth/SOURCES/sources.sha256
            forge/specs/azoth/nvidia/sources.sha256
```

- [ ] **Step 2: No auto-merge for a refresh**

In the `pr` job step "Branch, commit, PR with auto-merge", replace:

```yaml
          title="chore(kernel): bump $(paste -sd, - <<< "$keys" | sed 's/,/, /g')"
```

with:

```yaml
          title="chore(kernel): bump $(paste -sd, - <<< "$keys" | sed 's/,/, /g')"
          outcome=$(cat prep-outcome)
          [[ $outcome != REFRESH ]] || title+=" (patch refresh needed)"
```

and replace:

```yaml
          gh pr merge --auto --squash "$url"
          echo "PR: ${url} (auto-merge once the Kernel gate check is green)" | tee -a "$GITHUB_STEP_SUMMARY"
```

with:

```yaml
          if [[ $outcome == REFRESH ]]; then
            echo "PR: ${url} (patch refresh needed: no auto-merge, a person merges after reviewing the refreshed copy)" | tee -a "$GITHUB_STEP_SUMMARY"
          else
            gh pr merge --auto --squash "$url"
            echo "PR: ${url} (auto-merge once the Kernel gate check is green)" | tee -a "$GITHUB_STEP_SUMMARY"
          fi
```

- [ ] **Step 3: Lint the workflow**

Run: `actionlint .github/workflows/kernel-bump.yml && python3 -B scripts/verify.py workflows 2>&1 | grep -F kernel-bump.yml`

Expected: actionlint prints nothing and exits 0. The grep prints nothing, meaning verify.py has no finding for this file.

- [ ] **Step 4: Check the classification against the real log**

The outcome logic is three lines of shell; check it against a log shaped like Task 1 Step 6:

Run: `printf 'x\nbuild.sh: refresh needed: sched/0001-bore-cachy.patch (it no longer applies without fuzz)\n' > "$SCRATCH/prep.log" && outcome=FAIL && if grep -q '^build.sh: refresh needed: ' "$SCRATCH/prep.log"; then outcome=REFRESH; fi && echo "$outcome"`

Expected: `REFRESH`

- [ ] **Step 5: Commit**

```bash
git -C /var/home/hr-mes/athanor add .github/workflows/kernel-bump.yml
git -C /var/home/hr-mes/athanor commit -m "ci(kernel-bump): open a patch refresh bump without auto-merge" -m "When prep stops with 'refresh needed', the bump PR says so in its title and body and does not enable auto-merge: the refreshed copy is reviewed and the PR merged by a person." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 3: Record the rule in the kernel documentation

**Files:**
- Modify: `docs/architecture/doc_kernel_build.md`, sections 1, 2, 3, 8 and 13 (Italian).
- Modify: `forge/specs/azoth/KERNEL.md`, directory table (Italian).

**Interfaces:**
- Consumes: the stage name `refresh`, the directory `patches/refreshed/`, the preamble line `Upstream-SHA256:`, the message `refresh needed`, the title suffix ` (patch refresh needed)` (Tasks 1 and 2).
- Produces: documentation only.

- [ ] **Step 1: Section 1, principle 3**

Replace:

```markdown
   Makefile, niente `-Wno-error`, objtool acceso. Una patch che non si applica
   fa fallire la build (`git apply` è senza fuzz), non viene "saltata".
```

with:

```markdown
   Makefile, niente `-Wno-error`, objtool acceso. Una patch che non si applica
   fa fallire la build (`git apply` è senza fuzz), non viene "saltata". Una patch
   di terzi che smette di entrare si rinfresca una volta, con revisione umana, e
   la copia rinfrescata entra anch'essa senza fuzz (sezione 8).
```

- [ ] **Step 2: Section 2, file table**

After the `patches.list` row, insert:

```markdown
| `patches/refreshed/`     | copie rinfrescate delle patch di `patches.list` che non entrano più senza fuzz, stesso percorso relativo; il preambolo registra commit e SHA-256 del file upstream da cui derivano (sezione 8) |
```

- [ ] **Step 3: Section 3, steps 2 and 3**

Replace:

```markdown
2. scrive `~/.rpmmacros` con `%_topdir` e `%buildid .azoth`; `rpm -i` del SRPM;
   `dnf builddep -y SPECS/kernel.spec` con gli stessi bcond di rpmbuild, subito,
   perché la derivazione del config deve vedere la toolchain vera (rust-src,
   bindgen, pahole: `RUST_IS_AVAILABLE` e le opzioni che ne dipendono);
```

with:

```markdown
2. scrive `~/.rpmmacros` con `%_topdir` e `%buildid .azoth`; `rpm -i` del SRPM;
   `dnf builddep -y SPECS/kernel.spec` con gli stessi bcond di rpmbuild, dopo le
   patch (passo 3) e prima della derivazione del config, che deve vedere la
   toolchain vera (rust-src, bindgen, pahole: `RUST_IS_AVAILABLE` e le opzioni che
   ne dipendono): una patch che non entra ferma prep in pochi secondi;
```

Replace:

```markdown
   sull'indice, diff dal commit Fedora al risultato. `patches.list` e `patches/`
```

with:

```markdown
   sull'indice (per ogni voce di `patches.list` la copia in `patches/refreshed/`
   se esiste, rifiutata se registra un altro file upstream o se il file upstream
   entra di nuovo senza fuzz), diff dal commit Fedora al risultato. `patches.list` e `patches/`
```

- [ ] **Step 4: Section 8, the refresh flow**

In section 8, replace:

```markdown
   derivazione del config e gate di `kernel-local`. L'esito e le opzioni
   derivate (`listnewconfig` con i valori CachyOS) vanno nel corpo della PR,
   verde o rosso.
```

with:

```markdown
   derivazione del config e gate di `kernel-local`. L'esito e le opzioni
   derivate (`listnewconfig` con i valori CachyOS) vanno nel corpo della PR,
   verde o rosso. Se prep si ferma con `refresh needed`, l'esito è `REFRESH`.
```

After the paragraph that starts with `Il gate della PR è il check \`Kernel gate\`` and ends with `restano PR umane.`, insert:

```markdown
**Patch da rinfrescare** (decisione del maintainer, 2026-09-14). Una patch di
`patches.list` che non entra più senza fuzz non si applica con tolleranza: la
tolleranza indovina il punto e un bot che unisce da solo la porterebbe nel kernel
senza che nessuno la guardi. Con esito `REFRESH` la PR ha il titolo che finisce con
`(patch refresh needed)` e **non** ha l'auto-merge. Sul branch della PR, nel
builder, `build.sh --stage refresh --out DIR` ricostruisce l'albero unito vero,
applica ogni patch che non entra con GNU `patch --fuzz=2` come proposta, verifica
che la copia proposta entri senza fuzz in entrambi gli alberi (indice Fedora e
albero CachyOS) e la scrive in `DIR/refreshed/` con il resoconto di GNU patch. Una
persona legge ogni hunk applicato con fuzz, copia il file in
`forge/specs/azoth/patches/refreshed/` con lo stesso percorso di `patches.list`, fa
il commit sul branch e, con il `Kernel gate` verde, fa il merge a mano. Il
preambolo della copia registra il commit di `CachyOS/kernel-patches`, lo SHA-256
del file upstream e i pin su cui è stata rinfrescata. La build rifiuta una copia
che registra un altro file upstream (CachyOS ha cambiato la patch: si rinfresca di
nuovo) e una copia diventata inutile (il file upstream entra di nuovo senza fuzz:
si cancella). Se GNU patch non riesce nemmeno con fuzz, o se i due alberi
richiedono copie diverse, `refresh` si ferma e la patch si rinfresca a mano.
```

- [ ] **Step 5: Section 13, the decision**

At the end of the numbered list in section `## 13. Decisioni del maintainer (2026-09-03)`, after item 4, add:

```markdown
5. (2026-09-14) Patch di terzi: niente fuzz nella build, mai. Quando una patch di
   `patches.list` smette di entrare si rinfresca una volta con `build.sh --stage
   refresh`, una persona rivede gli hunk applicati con fuzz e la copia va in
   `patches/refreshed/`; la PR di bump in quel caso non ha l'auto-merge (sezione 8).
   Primo caso: la patch BORE della serie 7.2 su `include/linux/sched.h` di
   cachyos-7.2.5-1, che ha aggiunto `struct task_ipi_mask` davanti a `struct
   task_struct`.
```

- [ ] **Step 6: KERNEL.md**

In `forge/specs/azoth/KERNEL.md`, after the row that starts with `| \`patches.list\` |`, insert:

```markdown
| `patches/refreshed/` | copie rinfrescate e riviste delle patch di `patches.list` che non entrano più senza fuzz; il preambolo registra il file upstream da cui derivano (`build.sh --stage refresh`, spec sezione 8) |
```

In the `build.sh` row, replace:

```markdown
`prep` (sorgenti, patch, gate dei config),
```

with:

```markdown
`prep` (sorgenti, patch, gate dei config), `refresh` (propone le copie rinfrescate delle patch di CachyOS che non entrano senza fuzz),
```

- [ ] **Step 7: Verify links and formatting**

Run: `python3 -B scripts/verify.py docs 2>&1 | grep -E "doc_kernel_build|KERNEL.md"`

Expected: no output.

Run: `grep -c "refresh" docs/architecture/doc_kernel_build.md forge/specs/azoth/KERNEL.md`

Expected: `docs/architecture/doc_kernel_build.md:` followed by a number of at least 5, and `forge/specs/azoth/KERNEL.md:` followed by a number of at least 2.

- [ ] **Step 8: Commit**

```bash
git -C /var/home/hr-mes/athanor add docs/architecture/doc_kernel_build.md forge/specs/azoth/KERNEL.md
git -C /var/home/hr-mes/athanor commit -m "docs(kernel): record the patch refresh rule" -m "Third-party patches never apply with fuzz; one that stops applying is refreshed once with build.sh --stage refresh, reviewed and committed under patches/refreshed, and its bump PR is merged by a person (maintainer decision, 2026-09-14)." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 4: Refresh BORE for 7.2.5, with the maintainer's review

**Files:**
- Create: `forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch`

**Interfaces:**
- Consumes: `build.sh --stage refresh` and the strict resolution (Task 1).
- Produces: the committed refreshed copy; prep on the 7.2.5 pins passes.

- [ ] **Step 1: Generate the copy**

Run: `builder bash forge/specs/azoth/build.sh --stage refresh --out /out 2>&1 | tail -3`

Expected: `sched/0001-bore-cachy.patch: refreshed copy written to /out/refreshed/sched/0001-bore-cachy.patch` and the `refresh done` step.

- [ ] **Step 2: Show the fuzzed hunk to the maintainer and wait for approval**

Extract what the maintainer must review:

Run: `sed -n '1,/^diff --git/p' "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch" | grep -E "Refreshed|Upstream|fuzz|offset"` and `awk '/^diff --git a\/include\/linux\/sched.h/,/^diff --git a\/include\/linux\/sched\/bore.h/' "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch" | head -45`

Expected:
- the report shows `Hunk #1 succeeded at 835 with fuzz 2 (offset 11 lines).` for `include/linux/sched.h`;
- in the hunk, the `+#ifdef CONFIG_SCHED_BORE` block sits after the `struct task_ipi_mask` definition (`#endif` followed by a blank line) and before `struct task_struct {`.

STOP: present both outputs to the maintainer and continue only after explicit approval of the placement.

- [ ] **Step 3: Commit the reviewed copy and run full prep (GREEN)**

Run: `mkdir -p forge/specs/azoth/patches/refreshed/sched && cp "$SCRATCH/azoth-out/refreshed/sched/0001-bore-cachy.patch" forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch`

Run: `builder bash forge/specs/azoth/build.sh --stage prep --out /out 2>&1 | tail -3; echo "exit ${PIPESTATUS[0]}"`

Expected: the run passes the patches, `BuildRequires of kernel.spec`, the config derivation and `rpmbuild -bp`, and ends with the `>>> done:` step listing `kernel-local` and the generated config, then `exit 0`. Any other failure, for example in `patches/` or in the config gate, is a separate finding: stop and report it.

- [ ] **Step 4: Commit**

```bash
git -C /var/home/hr-mes/athanor add forge/specs/azoth/patches/refreshed/sched/0001-bore-cachy.patch
git -C /var/home/hr-mes/athanor commit -m "feat(kernel): refresh the BORE patch for cachyos-7.2.5-1" -m "cachyos-7.2.5-1 adds struct task_ipi_mask right before struct task_struct in include/linux/sched.h, where 7.2/sched/0001-bore-cachy.patch at CachyOS/kernel-patches 9bf8104a inserts its structures, so the upstream hunk no longer applies without fuzz. GNU patch placed it with fuzz 2 after task_ipi_mask; the placement was reviewed by the maintainer. Every other hunk applies unchanged." -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EUnNXqv8jNWDVMA83G7eZ4"
```

---

### Task 5: Ship the bump through PR #29

**Files:** none changed; this task publishes Tasks 1–4.

**Interfaces:**
- Consumes: the commits of Tasks 1–4 on `bump/kernel-20260914-1919`.
- Produces: Azoth 7.2.5 published, with NVIDIA modules and a system image built on it.

Every step here is outward: get the maintainer's consent before Step 1 and before the merge in Step 3.

- [ ] **Step 1: Disable auto-merge, push, retitle**

```bash
gh pr merge 29 --repo hr-mes/athanor --disable-auto
git -C /var/home/hr-mes/athanor push origin bump/kernel-20260914-1919
gh pr edit 29 --repo hr-mes/athanor --title "chore(kernel): bump to 7.2.5 with the patch refresh rule (patch refresh needed)"
```

Then append this note to the PR body with `gh pr comment 29 --repo hr-mes/athanor --body-file <file>`:

```markdown
Prep failed because `7.2/sched/0001-bore-cachy.patch` no longer applies without fuzz to `include/linux/sched.h` of cachyos-7.2.5-1. This branch now carries:

- `build.sh`: third-party patches still apply strictly; `--stage refresh` proposes refreshed copies with GNU patch for review; committed copies under `patches/refreshed/` are tied to the hash of their upstream file, and stale or obsolete copies stop the build.
- `kernel-bump.yml`: a bump that needs a refresh is labelled in its title and never auto-merged.
- `doc_kernel_build.md` and `KERNEL.md`: the rule (maintainer decision, 2026-09-14).
- `patches/refreshed/sched/0001-bore-cachy.patch`: the BORE patch refreshed for 7.2.5. One hunk used fuzz 2 (`include/linux/sched.h`, after `struct task_ipi_mask`), and the maintainer reviewed it.

Merged by hand once the Kernel gate is green.
```

- [ ] **Step 2: Wait for the Kernel gate**

Run: `gh pr checks 29 --repo hr-mes/athanor --watch --interval 60`

Expected: `Kernel gate` passes, together with `inputs`, `build` (a full build, because the inputs changed), `boot` and `kmod`. A failing `build` or `boot` is a finding to investigate (superpowers:systematic-debugging), not something to retry blindly.

- [ ] **Step 3: Merge (maintainer consent) and follow publication**

```bash
gh pr merge 29 --repo hr-mes/athanor --rebase
```

After the merge, in order:
1. **Kernel Build on `iso-v0`:** it publishes `azoth:7.2.5-100.azoth.fc43` and then starts `nvidia-kmod.yml`. Watch it with `gh run list --repo hr-mes/athanor --workflow kernel-build.yml --branch iso-v0 --limit 1`, then `gh run watch <id> --repo hr-mes/athanor --exit-status`.
2. **NVIDIA kmod:** its `sign` job waits for approval of the `signing` environment. The maintainer approves on the run page.
3. **Orchestrator:** it may have raced the kernel publish, because the push to `forge/**` also starts it. When `nvidia-kmod.yml` has published, re-dispatch it with `gh workflow run athanor-forge-orchestrator.yml --repo hr-mes/athanor --ref iso-v0`. Its system image job also waits for signing approval.
4. **Verify the image:**

   Run: `podman pull -q ghcr.io/hr-mes/athanor-system:latest >/dev/null && podman run --rm ghcr.io/hr-mes/athanor-system:latest rpm -q kernel-core`

   Expected: `kernel-core-7.2.5-100.azoth.fc43.x86_64`

---

## Self-Review

1. **Spec coverage:** each part of the approved design has a task.
   - Strict application stays in `build.sh`: Task 1 Step 4, the `applies` check before every `git apply`.
   - The refresh proposes a copy on the real merged tree with GNU patch, and reports the fuzzed hunks: Task 1 `refresh_copy`, with the report in the preamble.
   - The copy is tied to its upstream commit and file hash: `Refreshed-From` and `Upstream-SHA256`.
   - A stale copy stops the build: Task 1 Step 8.
   - An obsolete copy stops the build: Task 1 Step 9.
   - Human review and commit: Task 4 Step 2 STOP.
   - The bot opens a labelled PR with no auto-merge: Task 2.
   - The rule is recorded in sections 1, 2, 3, 8 and 13: Task 3.
   - PR #29 is unblocked: Tasks 4–5.
2. **Placeholder scan:** every code step contains its code, every command states its expected output, and the STOP in Task 4 is an intended human gate.
3. **Type consistency:** the same names are used across tasks.
   - Message `build.sh: refresh needed: <path> (` is produced by Task 1 and grepped by Task 2.
   - Stage `refresh` is used in Tasks 1, 3 and 4.
   - Directory `patches/refreshed/` is used in Tasks 1, 3 and 4.
   - Preamble key `Upstream-SHA256:` is used by Task 1 and documented in Task 3.
   - File `prep-outcome` and outcome values `ok`, `FAIL` and `REFRESH` are used in Task 2 and in section 8 of Task 3.
