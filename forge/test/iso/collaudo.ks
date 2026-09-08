# Unattended kickstart for the ISO acceptance test. It is never part of the published
# ISO: the shipped installer stays attended on purpose, because the person installing
# Athanor has to see and answer what is being done to their disk. This file is handed to
# the installer at boot time instead, through inst.ks= on the kernel command line, so the
# very ISO that ships is the one under test.
#
# It includes the kickstart the builder wrote into the ISO rather than restating it:
# that file carries the ostreecontainer line and the pinned `bootc switch`, which are the
# two things the test exists to exercise. A copy here would be a copy that can drift, and
# a test that installs something other than what the ISO installs is worth nothing.
# Everything added below is only what a human would otherwise type: disk, timezone, and
# an account to log in with.
#
# The include reaches into the ISO's own mount point, which is where the installer's
# kickstart already reads it from: the file that ships is itself
# "%include /run/install/repo/osbuild-base.ks" followed by a %post. So this path is
# resolvable at include time on this media, and that is observed rather than assumed.

%include /run/install/repo/osbuild-base.ks

# Boot to the greeter, the same line the shipped ISO's kickstart carries. It has to be
# repeated rather than inherited: the ISO holds two files, and the include below reaches
# osbuild-base.ks, while the installer customisation lands in /osbuild.ks alongside it.
# Anaconda otherwise finds no display manager among the packages it installs -- an
# ostreecontainer install installs none -- and falls back to multi-user.target, which is
# what left greetd enabled and dead in runs 34269959759 and 34275504878.
xconfig --startxonboot

# The whole disk, no questions. The test VM has one virtio disk and nothing to preserve.
clearpart --all --initlabel
autopart --type=btrfs
timezone UTC --utc
keyboard us
lang en_US.UTF-8

# The account the greeter check logs in as. This password never leaves the test VM, which
# is created and destroyed inside one job; it is not a credential of anything.
# Give the installed system a serial console. Without this the test is blind after the
# restart: console=ttyS0 is on the installer's kernel command line only, the installed
# system does not inherit it, and its own kargs carry no console= at all. The serial log
# then stops the moment systemd starts a getty, which is why run 34262503262 recorded no
# multi-user.target and no graphical.target anywhere -- not a boot that stalled, a log
# that ended. The greeter markers this test waits for could never have arrived.
#
# It belongs here rather than in athanor-base-config's kargs.d, because a serial console
# is a property of this test VM, not of Athanor: a real laptop has no ttyS0 to talk to.
bootloader --append="console=tty0 console=ttyS0,115200n8"

user --name=collaudo --password=collaudo --plaintext --groups=wheel
rootpw --lock

# Restart into the installed system rather than stopping at the summary, so the same run
# proves the second half: that what was written to the disk boots.
reboot --eject

%post --erroronfail
set -eu
# The greeter check reads the installed system over the serial console, so the console
# has to exist on it too, not only in the installer.
if [ -c /dev/ttyS0 ]; then
    echo "Athanor kickstart finished" > /dev/ttyS0
fi
%end
