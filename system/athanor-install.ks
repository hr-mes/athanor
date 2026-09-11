# Kickstart for Athanor OS bare-metal, interactive install.
#
# This kickstart is public: it must not carry any one person's account, password or
# disk. It sets what defines the system -- the bootc image, the hardened boot line,
# the TPM monotonic counter -- and leaves what belongs to the person -- keyboard,
# time zone, disk layout and the user account -- to Anaconda's interactive screens.
#
# Anaconda goes interactive for exactly the directives that are absent here: with no
# `part`/`autopart`/`clearpart` it asks for the disk, and with no `user` it asks the
# person to create their account in the GUI. The home directory it creates is
# encrypted and sealed to the TPM automatically at first boot by
# athanor-tpm-luks-seal.service (PCRs 0,2,7,11), so nothing about the account needs to
# be scripted here.

lang en_US.UTF-8

# The hardened kernel command line: IOMMU on, kernel lockdown in integrity mode,
# module signature enforcement, and the memory-safety mitigations Athanor ships with.
# module.sig_enforce=1 + lockdown=integrity are why the Azoth kernel and the NVIDIA
# modules must be signed and the project MOK enrolled at first boot.
bootloader --append="quiet splash fastboot iommu=pt intel_iommu=on amd_iommu=on efi=disable_early_pci_dma zswap.enabled=1 zswap.compressor=zstd rootflags=noatime slab_nomerge pti=on randomize_kstack_offset=on vsyscall=none debugfs=off oops=panic module.sig_enforce=1 lockdown=integrity init_on_free=1"

# The bootc image is the identity of the system, not a user choice. Pin it to the
# release being shipped rather than :latest, which on a non-default branch may resolve
# to a different or older build.
ostreecontainer --url=ghcr.io/hr-mes/athanor-system:latest --transport=registry

# The root account stays locked: administration is through the wheel user Anaconda
# creates. No user is declared here, so Anaconda asks the installer to create one.
rootpw --lock

firewall --enabled --default=drop --service=ssh
services --enabled=sshd,systemd-homed

# Disk layout is the installer's choice: no clearpart/part/autopart here, so Anaconda
# opens its partitioning screen. systemd-homed encrypts the user's home (LUKS2), and
# athanor-tpm-luks-seal.service seals it to the TPM at first boot.

reboot

%post --erroronfail
# The one piece of provisioning that is the system's, not the user's: the TPM 2.0
# monotonic counter the rollback protection reads (NV index 0x01800001). Enrolling the
# LUKS home to the TPM is done at first boot by athanor-tpm-luks-seal.service, once the
# user Anaconda created actually exists, so it is not repeated here.
if command -v tpm2_getcap >/dev/null 2>&1 && tpm2_getcap properties-fixed | grep -q "TPM2_PT_TOTAL_COMMANDS"; then
    echo "Initialising the TPM2 monotonic counter at NV index 0x01800001..."
    tpm2_nvundefine 0x01800001 -C o 2>/dev/null || true
    tpm2_nvdefine 0x01800001 -C o -s 8 -a "ownerread|ownerwrite|authread|authwrite|nt=counter"
    tpm2_nvincrement 0x01800001 -C o
fi
%end
