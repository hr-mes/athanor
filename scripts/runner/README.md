# Self-hosted runner

The `self-hosted` jobs of the kernel workflows (`kernel-build.yml`, `nvidia-build.yml`,
`kernel-weekly.yml`, `kernel-bump.yml`) run on this runner. The repository is public
and a runner executes workflow code, so it lives in an ephemeral KVM guest, never on the
host itself.

## How it works

- `athanor-runner.service` runs `vm.sh` as a dynamic user, with no access to the host
  beyond `/dev/kvm`, its own state, runtime and log directories, and the network.
- For every job `vm.sh` asks GitHub for a just-in-time runner configuration
  (`generate-jitconfig`), valid for one job only, and boots the base image with
  `snapshot=on`: nothing the job writes to the system disk survives it.
- QEMU passes the configuration to the guest as the systemd credential `jitconfig`
  (`fw_cfg`); `actions-runner.service` in the guest runs the job and powers the guest
  off. The service restarts `vm.sh`, which boots a clean guest for the next job.
- Two extra disks: `cache.raw` persists across jobs (podman storage, `~/.cache/azoth`),
  `scratch.raw` is recreated empty before every job (the work directory).
- The GitHub token is a service credential encrypted with the host key and the TPM2
  (`/etc/credstore.encrypted/athanor-runner.github-token`), used only to create and
  remove runner registrations.
- Pull requests from forks never reach the runner: the self-hosted jobs of
  `kernel-build.yml` skip them, and the repository requires approval for every outside
  contributor.

Pins and sizing are in `runner.env`: Fedora Cloud Base and actions/runner by SHA-256,
12 vCPUs and 20 GB, CPU and I/O weights that leave the desktop responsive.

## Install

```sh
bash scripts/runner/build-image.sh
gh auth token | sudo scripts/runner/install.sh --image ~/.cache/athanor-runner/golden.qcow2
journalctl -fu athanor-runner.service
```

The guest serial console of the current job is `/var/log/athanor-runner/console.log`.

## Update

Change the pins in `runner.env`, rebuild the image and run `install.sh` again. A new
token (after `gh auth refresh` or a new PAT) needs `install.sh` again as well.

## Remove

```sh
sudo systemctl disable --now athanor-runner.service
sudo rm -rf /etc/systemd/system/athanor-runner.service /usr/local/libexec/athanor-runner \
  /etc/credstore.encrypted/athanor-runner.github-token /var/lib/private/athanor-runner \
  /var/log/private/athanor-runner
sudo systemctl daemon-reload
```
