# Unattended kickstart of the development VM (scripts/devvm/README.md). create.sh fills in
# @USER@ and @SSH_KEY@ and hands it to the published ISO the way the acceptance test hands
# over forge/test/iso/collaudo.ks: on a disk labelled ATHANORKS, named by inst.ks= on the
# GRUB command line. It follows collaudo.ks line for line except where a development VM
# differs from a one-shot test VM, and those lines say so.
#
# FOR THE DEVELOPMENT VM ONLY. The account has a password equal to its name and
# passwordless sudo, which is acceptable for a guest reachable only from the host
# (user-mode network, SSH forwarded on 127.0.0.1) and wrong anywhere else.

# The builder's own kickstart: the ostreecontainer line and the pinned `bootc switch`, so
# the VM runs exactly what the ISO installs.
%include /run/install/repo/osbuild-base.ks

xconfig --startxonboot
clearpart --all --initlabel
autopart --type=btrfs
timezone UTC --utc
keyboard us
lang en_US.UTF-8
bootloader --append="console=tty0 console=ttyS0,115200n8"

# The developer: the host user's name, so ssh needs no user@. The password is for the
# greeter; SSH takes the key only.
user --name=@USER@ --password=@USER@ --plaintext --groups=wheel
sshkey --username=@USER@ "@SSH_KEY@"
rootpw --lock
services --enabled=sshd

# Power off rather than restart: QEMU exits, create.sh knows the install is over, and the
# first boot happens on the overlay start.sh boots.
poweroff

%post --erroronfail
set -eu
# Passwordless sudo for deploy.sh and ssh.sh. Development VM only, see the header.
echo '@USER@ ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/90-devvm
chmod 0440 /etc/sudoers.d/90-devvm
if [ -c /dev/ttyS0 ]; then
    echo "Athanor devvm kickstart finished" > /dev/ttyS0
fi
%end
