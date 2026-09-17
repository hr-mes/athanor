# Build ordering: kernel, NVIDIA modules, system images

Status: **approved on 2026-09-17.** The maintainer delegated the review. This second version replaces a first draft that an adversarial review found to fail open. The document amends:

- `doc_kernel_build.md`, section 10 (publication of `azoth-nvidia`);
- `doc_system_image.md`, S6 and S8.

Section 5 lists the changes those documents take.

## 1. Context

Three workflows produce what a system image is built from, and nothing orders them.

- **Kernel Build** (`kernel-build.yml`) runs on a push to `forge/specs/azoth/**`. It publishes `azoth:<nvr>`, or reuses it when the attested inputs match. On success it dispatches NVIDIA kmod and does not wait for it.
- **NVIDIA kmod** (`nvidia-kmod.yml`) runs only on dispatch. It:
  - builds the open and legacy modules against `azoth-devel:<nvr>`;
  - signs them in the `signing` environment, which needs a maintainer approval;
  - boots them;
  - overwrites `azoth-nvidia:<nvr>-open` and `azoth-nvidia:<nvr>-legacy`.
- **Athanor Forge Orchestrator** runs on a push to `forge/**` or `system/**`, on dispatch, and daily at 04:00 UTC. It has `cancel-in-progress`.
  - `build-repo` pulls `azoth:<nvr>` by tag into tier 0 (`forge/scripts/fetch_repo_rpms.sh`). It exits with `[FATAL] Image not found` when the tag is missing.
  - `dag-system-image` asks for the `signing` approval. It then copies the modules with `FROM azoth-nvidia:<nvr>-<branch>`, by tag.

A merged kernel bump touches `forge/specs/azoth/**`, which is also under `forge/**`, so Kernel Build and the Orchestrator start together.

What goes wrong today:

1. **Kernel NVR moves.** The Orchestrator reaches tier 0 or `FROM` before the kernel or the modules exist, and goes red. Someone has to rerun it after both workflows finish.
2. **Only an NVIDIA version moves.** The module tag is keyed by the kernel alone. The Orchestrator copies the old modules, and `system/nvidia/gate.sh` stops the build. The cycle stays red until someone reruns it.
3. **Nothing moves.** Every Kernel Build dispatches NVIDIA kmod, which rebuilds the modules, asks for a second approval and overwrites the tags.
   - The two variants, built minutes apart, can copy modules from different publications.
   - The inputs are read by tag at different moments, so a published image is not reproducible from them.
4. **Cancellation.** The Orchestrator's `cancel-in-progress` can cancel a cycle while it pushes images. NVIDIA kmod's group `nvidia-${ref}` can cancel a run between the push and the signature, leaving a tag with no signature.
5. **Retention.** Several cleanups can delete what a build relies on.
   - `forge/specs/azoth/retention.sh` prunes `azoth-nvidia` from Kernel Build, in a different concurrency group from the kmod run that is attaching signatures.
   - `forge-ghcr-cleanup.yml` keeps two tagged versions per package and deletes every untagged manifest, cosign bundles included. It currently fails on its token; once that is fixed it would delete them.

No wrong image is published today: tier 0, `FROM` and the gate all fail closed. But the order holds by chance, red cycles need a human, and a no-op push costs an extra approval.

## 2. Decisions

**O1. One chain, one owner.** The Orchestrator is the only workflow that turns a kernel into modules and images.

- **Push triggers:** the Orchestrator no longer triggers on pushes that touch only `forge/specs/azoth/**`.
- **Kernel Build:** on a push, once `azoth:<nvr>` is published or reused, it dispatches the Orchestrator on the same ref instead of NVIDIA kmod.
- **NVIDIA kmod:** becomes a reusable workflow (`workflow_call`) that the Orchestrator calls when the modules are missing. It keeps `workflow_dispatch` for manual runs.

A dispatch with `GITHUB_TOKEN` starts runs; `workflow_run` would fire only from the default branch, and `iso-v0` is the working branch.

**O2. Artifacts are identified by digest.** The module tag carries what the modules were built against:

`azoth-nvidia:<nvr>-k<first 12 hex of the azoth:<nvr> digest>-open-<NVIDIA_OPEN_VERSION>`

and the same with `-legacy-<NVIDIA_LEGACY_VERSION>`. A republished kernel with the same NVR therefore gets new tags and never collides with the old ones.

- **The predicate:** the custom predicate NVIDIA kmod signs records the digests of `azoth:<nvr>` and `azoth-devel:<nvr>` that it actually pulled, both by digest.
- **Immutability:** a tag that exists with a valid signature and attestation is never overwritten. A tag that exists without them is left over from an interrupted run, and a new run may overwrite it.

**O3. One script decides, with three answers.** `system/kernel-artifacts.sh` resolves the inputs of the current pins and writes them as digests to a file in a known directory, with one of three exit codes:

| Exit | Meaning |
|---|---|
| 0 | the kernel and both module tags exist, are signed and carry an attestation matching the pins and the kernel digest |
| 3 | the kernel exists and is signed, but a module tag is missing or has no valid signature or attestation |
| 4 | the kernel is missing for the pinned NVR |
| any other | an error (registry, Rekor, network, malformed data): the calling job fails |

- **Retries:** registry and Rekor calls go through `retry.sh`. A persistent outage is a red run, never a skip.
- **Callers:** the Orchestrator (O4), NVIDIA kmod at its start (O5) and System Image Check (O7) call this one script. Kernel Build does not decide anything about modules any more.

**O4. The Orchestrator pipeline.** A job `kernel-artifacts` runs first, outside the `signing` environment, and everything that reads the kernel depends on it.

- **Exit 0:** `build-repo` and `dag-system-image` run. Tier 0 pulls `azoth@<digest>` and `system/build-image.sh` passes the module digests as build arguments, all from the file of O3. The image is built from exactly what was verified.
- **Exit 3:** the Orchestrator calls NVIDIA kmod with the kernel digest, then runs the script again and proceeds as for exit 0. One cycle asks for two approvals: the module signature and the image signature.
- **Exit 4:** the run fails, unless a Kernel Build run for the same commit is queued or in progress (`gh run list`). In that case the run ends with a notice and no image, because Kernel Build dispatches the Orchestrator once the kernel is published (O1). This covers a push that touches both `forge/specs/azoth/**` and `system/**`.
- **The input `has_changes`:** checked when the plan is written. If the brain can decide there is nothing to build on a dispatch from Kernel Build, the dispatch passes an input that forces the image job. Otherwise no input is added.

**O5. NVIDIA kmod refuses redundant work.**

- **At its start:** kmod calls the script. With exit 0 it ends with a notice: no build, no approval.
- **Kernel pinned by digest:** it builds against the kernel digest it was given, or the one the script resolved, not against a tag read later.
- **After the approval:** if the pins moved since the dispatch, so that the kernel of the current HEAD is not published, it ends with a notice.

**O6. Cancellation and retention.**

- **The Orchestrator:** `cancel-in-progress: false`. GitHub keeps one pending run per group, so a newer push supersedes a waiting run but never cancels one that is running.
- **NVIDIA kmod:** manual runs use a group without cancellation. When the Orchestrator calls kmod, kmod runs inside the Orchestrator's group.
- **One pruner for `azoth-nvidia`:** only NVIDIA kmod prunes it, after publishing. It keeps every tag whose attestation matches a retained `azoth` release, and the tags referenced by the last published system images on each branch.
- **`forge-ghcr-cleanup.yml`:** it excludes `azoth*`. Each package has one pruner.

**O7. System Image Check on PRs.** It calls the script of O3.

| Exit | What the check does |
|---|---|
| 0 | builds the three images |
| 3 (only an NVIDIA version moved) | builds the default image, skips the two variants, adds a warning annotation naming the missing tags |
| 4 (the kernel NVR moved) | skips every build and the package delta, adds a warning annotation. Kernel Build on the PR proves the kernel and the modules build and boot |
| any other | the check fails |

On a pin bump the variants are therefore built and gated only after the merge, in the Orchestrator, where they fail closed.

**O8. Bump PRs.**

- **Pure kernel or NVIDIA pin bumps:** they keep auto-merge on a green prep.
- **System base or lock bumps:** those that touch `system/Containerfile` or `system/nvidia/locks` stay without auto-merge. The reason is the package review of `doc_system_image.md` section 4, not ordering.

**O9. Portability.**

- **Registry and owner:** the `FROM` lines this touches in `system/Containerfile` take them from an `ARG` with the current value as default. The script reads the same variables.
- **Decisions stay out of YAML:** the workflows call the script and read its exit code and file. No decision logic is repeated in YAML.

**O10. Bootstrap.** The change touches `kernel-build.yml`, so its merge triggers Kernel Build. Kernel Build dispatches the Orchestrator. The script answers 3, because no O2 tags exist yet. The Orchestrator calls NVIDIA kmod and then builds the images: acceptance test 2 without a pin bump. Images published before the change keep working, because they copied their modules at build time.

## 3. Resulting order

| Event | Kernel Build | Orchestrator | Approvals |
|---|---|---|---|
| push to `system/**` or `forge/**` outside the kernel, pins unchanged | does not run | exit 0: builds | 1 |
| kernel pin bump merged | builds, publishes, dispatches | not triggered by the push; the dispatched run gets exit 3, calls kmod, builds | 2 |
| NVIDIA pin bump merged | reuses the kernel, dispatches | exit 3: calls kmod, builds | 2 |
| push touching kernel and `system/**` | builds, dispatches | push run: exit 4 with Kernel Build running, notice. Dispatched run: exit 3 or 0 | 2 or 1 |
| daily schedule | does not run | exit 0: builds. Exit 3: calls kmod. Exit 4 with no Kernel Build running: red | 1 or 2 |
| registry or Rekor outage | — | red | — |
| a module approval rejected | — | red at the kmod call | — |

## 4. Risks

- **Approvals in the same run:** two approvals arrive minutes apart in the same run on a pin bump. Both are needed; rejecting either makes the run red.
- **Queueing:** `cancel-in-progress: false` means a long cycle delays the next one instead of being cut. GitHub keeps only the newest pending run.
- **Variants on pin bumps:** they are tested only after the merge (O7).

**Out of scope:**
- **ISO acceptance `newest`:** after a failed cycle it silently picks an older ISO.
- **`athanor-system:latest` on `iso-v0`:** the tag also moves from `iso-v0` builds, unlike the kernel's main-only `:latest`.

Both deserve their own decision.

## 5. Changes to other documents

- **`doc_kernel_build.md` section 10:** NVIDIA kmod as a reusable workflow called by the Orchestrator, the tag form of O2, retention by NVIDIA kmod only.
- **`doc_system_image.md` S6 and S8:** the image is built from the digests written by `system/kernel-artifacts.sh`.
- **`doc_naming.md`:** the `azoth-nvidia` row names the new tag form.

## 6. Acceptance

1. A push to `system/**` with unchanged pins: one Orchestrator cycle, no NVIDIA kmod, one approval.
2. The bootstrap of O10, and later a kernel pin bump: Kernel Build dispatches the Orchestrator, which calls NVIDIA kmod once and publishes the three images. No run is red and no human reruns anything.
3. A manual NVIDIA kmod run for existing, attested tags ends with a notice, asks for no approval and leaves the digests unchanged.
4. A kernel republished with the same NVR produces new module tags; the old ones stay untouched.
5. `system/kernel-artifacts.sh` has tests for exits 0, 3, 4 and for a registry error, run in `call-lint.yml`.
