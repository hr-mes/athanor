# Build ordering: kernel, NVIDIA modules, system images

Status: **approved on 2026-09-17** (the maintainer delegated the review; approved after the amendments to O2, O3 and section 6 below). It amends `doc_kernel_build.md` (section 10, publication of `azoth-nvidia`) and `doc_system_image.md` (S6, S8); section 5 lists the changes those documents take.

## 1. Context

Three workflows produce what a system image is built from. Nothing orders them.

- **Kernel Build** (`kernel-build.yml`) runs on a push to `forge/specs/azoth/**`. It publishes `azoth:<nvr>`, or reuses it when the attested inputs match. On success it dispatches NVIDIA kmod and does not wait for it.
- **NVIDIA kmod** (`nvidia-kmod.yml`) runs only on dispatch. It builds the open and legacy modules against `azoth:<nvr>`. It signs them in the `signing` environment, which needs a maintainer approval, boots them, and pushes `azoth-nvidia:<nvr>-open` and `azoth-nvidia:<nvr>-legacy`.
- **Athanor Forge Orchestrator** runs on a push to `forge/**` or `system/**`, on dispatch and daily at 04:00 UTC. Its `system-image` job installs `azoth:<nvr>` in tier 0 (`forge/scripts/fetch_repo_rpms.sh`). It copies the modules from `azoth-nvidia:<nvr>-<branch>` (`system/Containerfile`). It asks for the `signing` approval before it builds.

A merged kernel bump touches `forge/specs/azoth/**`, which is also under `forge/**`: Kernel Build and the Orchestrator start together. On 2026-09-17 this was observed after PR #35. The pins had not moved, so it was harmless.

What goes wrong when they race, as the code stands:

1. **Kernel NVR moves.** The Orchestrator can reach tier 0 before `azoth:<nvr>` exists: `[FATAL] Image not found`. Or it reaches `FROM azoth-nvidia:<nvr>-open` before NVIDIA kmod published it. Either way the cycle is red and needs a manual rerun after both workflows finish.
2. **Only an NVIDIA version moves.** `azoth-nvidia:<nvr>-open` is keyed by the kernel alone, so the Orchestrator takes the old modules. `system/nvidia/gate.sh` stops the build on the version mismatch. The cycle is red until someone reruns it after NVIDIA kmod republishes the same tag.
3. **Nothing moves.** Every Kernel Build on a push dispatches NVIDIA kmod. Kmod rebuilds, re-signs and overwrites `azoth-nvidia:<nvr>-<branch>`, and asks for a second signing approval. The tag is mutable. The `nvidia` and `nvidia-legacy` variants, built minutes apart, can copy modules from two different publications. The published images are therefore not reproducible from their inputs.

No wrong image is published today: tier 0, `FROM` and the gate all fail closed. But the order holds by chance, a red cycle needs a human, and a no-op push costs an extra approval.

## 2. Decisions

**O1. Immutable module tags.** NVIDIA kmod publishes `azoth-nvidia:<nvr>-open-<NVIDIA_OPEN_VERSION>` and `azoth-nvidia:<nvr>-legacy-<NVIDIA_LEGACY_VERSION>`, with the versions taken from `forge/specs/azoth/pins.env`.

- A tag is written once and never overwritten.
- The existing `<nvr>-open` and `<nvr>-legacy` tags are no longer written. Images already published keep resolving them.
- `system/Containerfile` receives the two versions as build arguments from `system/build-image.sh`, which reads them from the pins. `AZOTH_NVR` already arrives the same way.

**O2. NVIDIA kmod runs only when its output is missing.** Kernel Build's `nvidia` job checks whether both tags of O1 exist for the pinned kernel NVR and driver versions. The check uses a cosign signature and attestation, the same way `inputs` decides `reuse` for the kernel.

- **What "attested" means:** the custom predicate that NVIDIA kmod already signs carries the driver, its version and the kernel release string. It gains the digest of the `azoth:<nvr>` image the modules were built against. Kernel Build republishes `azoth:<nvr>` without changing the NVR when its attested inputs change. Modules built against the previous image would then carry the same release string but different symbol versions, so a digest mismatch counts as missing.
- If both tags are present and their attestation matches the pinned versions and the current kernel digest, kmod is not dispatched: no rebuild and no signing approval.
- A missing or unattested tag dispatches it, as today.

**O3. The system image checks its inputs before it asks for a signature.** A new job in `call-system-image.yml` runs before `dag-system-image` and outside the `signing` environment. It calls a script under `system/`, `system/kernel-artifacts.sh`, which verifies that three signed images exist for the pins: `azoth:<nvr>` and both module tags of O1. The module tags must also carry the attestation of O2 for the current kernel digest.

- **All present:** the build proceeds as today.
- **Any missing:** the job writes a notice to the step summary naming the missing reference and saying that NVIDIA kmod will dispatch the Orchestrator once it has published. `dag-system-image` is skipped; the run does not go red and no signing approval is requested.

**O4. NVIDIA kmod dispatches the Orchestrator after it publishes.** When `publish` succeeds, kmod dispatches the Orchestrator on the same ref with `gh workflow run` and the `GITHUB_TOKEN`, as Kernel Build already dispatches kmod. The dispatch carries an input that forces the system image job.

- **Why an input is needed:** `forge/scripts/dag_orchestrator.py` sets `has_changes` from dirty DAG nodes only, so a dispatch that changed nothing in the DAG would otherwise skip the image.
- **Why not `workflow_run`:** it fires only from the default branch, and `iso-v0` is the working branch (`kernel-build.yml` records the same limit).

**O5. Resulting order.** On any push, the three workflows reach a single outcome regardless of which starts first:

| Kernel or NVIDIA pins moved? | Orchestrator on the push | NVIDIA kmod | Result |
|---|---|---|---|
| no | builds; artifacts exist (O3) | not dispatched (O2) | one cycle, one approval |
| yes | skips the image with a notice (O3) | builds, signs, publishes, dispatches (O4) | a second Orchestrator cycle builds the image; two approvals, both needed |
| yes, and kmod fails | skipped, notice | red | no image; the red kmod run is the signal |

A daily scheduled Orchestrator follows the same rule: it builds only on published inputs.

**O6. Bump PRs.** With O1–O5 the order no longer depends on a person.

- **Pure pin bumps:** the kernel or NVIDIA pins alone keep auto-merge on a green prep, as `kernel-bump.yml` does today.
- **System base or lock bumps:** those that touch `system/Containerfile` or `system/nvidia/locks` stay without auto-merge. That rule exists for the package review of `doc_system_image.md` section 4, not for ordering.

**O7. System Image Check on PRs.** The check calls the same `system/kernel-artifacts.sh`.

- **Kernel or NVIDIA pins moved:** the modules for them cannot exist before the merge. The check builds the default image, skips the two variants and adds a warning annotation that names the missing tags.
- **Anything else:** it builds all three, as today.

**O8. Bootstrap.** The change set touches `kernel-build.yml`, so its merge triggers Kernel Build and the Orchestrator together.

- **Kernel Build:** finds no O1 tags and dispatches NVIDIA kmod, which publishes them and dispatches the Orchestrator.
- **Orchestrator on the merge:** skips the image under O3.
- **The images published before the change:** keep working. They copied their modules at build time, and nothing reads the old `<nvr>-<branch>` tags at runtime.

The first run of the new scheme is therefore also its acceptance test 2 without a pin bump.

## 3. Risks

- **Cancelled cycle.** The Orchestrator uses `cancel-in-progress`. O4's dispatch can cancel a cycle that is still running on the same ref, such as the push cycle while it waits for an approval. That cycle had skipped or was about to skip the image under O3, so nothing is lost. A cycle cancelled while pushing images leaves a partial publication; that risk exists today and O5 does not widen it.
- **Registry growth.** Immutable tags accumulate: one pair per kernel NVR and driver version. Retention follows the policy `nvidia-kmod.yml` already applies to `azoth-nvidia`, extended to the new tag form.
- **Variants untested before merge on a pin bump.** Under O7 a PR that moves a kernel or NVIDIA pin cannot build the two variants. Their build and `gate.sh` run in the dispatched cycle after the merge, and fail closed there. No broken image is published, but the failure appears after the merge instead of on the PR.
- **Dispatch token.** `gh workflow run` with `GITHUB_TOKEN` needs `actions: write` in the `publish` job of NVIDIA kmod. No PAT is added.

## 4. Out of scope

- **Forge Auto-Update Specs.** It fails daily because `GITHUB_TOKEN` may not open PRs. It is a separate fix.
- **scx.** `scx_loader` and `scx_lavd` come in their own PR, after the GPU migration (maintainer, 2026-09-16).

## 5. Changes to other documents

- **`doc_kernel_build.md` section 10:** the module tag scheme of O1, and the dispatch condition of O2.
- **`doc_system_image.md` S6 and S8:** the image build reads the module tags of O1, and runs the preflight of O3 before signing.
- **`doc_naming.md`:** the `azoth-nvidia` row names the new tag form.

## 6. Acceptance

1. A push that moves no pin runs one Orchestrator cycle and no NVIDIA kmod: one signing approval.
2. A kernel NVR bump pushed to `iso-v0`:
   - the push cycle skips the image with the notice of O3;
   - NVIDIA kmod publishes both O1 tags and dispatches the Orchestrator;
   - the dispatched cycle builds and publishes the three images;
   - no run is red.
3. Rerunning NVIDIA kmod for tags that exist leaves their digests unchanged.
3a. Republishing `azoth:<nvr>` with a new digest makes the next Kernel Build dispatch NVIDIA kmod (O2), and the O3 check refuses the old module tags until then.
4. `system/kernel-artifacts.sh` has tests for present, missing and unsigned references, run in `call-lint.yml` next to the NVIDIA tests.
