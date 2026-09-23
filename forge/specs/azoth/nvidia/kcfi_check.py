#!/usr/bin/env python3
"""kCFI type check of NVIDIA's open modules (docs/architecture/doc_kernel_build.md, section 10).

Under kCFI an indirect call traps when the function type at the call site differs
from the type of the target. NVIDIA does not build its RM code with kCFI, so it
carries such mismatches. This check fails on the kinds that can be found in the
source and in the build logs:

  bindata   a generated g_bindata_* getter defined with a type other than the one
            its NVOC header declares (the getters are stored in typed HAL slots);
  exports   an entry of the NVOC exported-method tables whose function arity does
            not match paramSize (resControl casts the entry back by paramSize);
  casts     a -Wcast-function-type-strict warning that is not one of the reasoned
            exceptions below;
  enums     any -Wincompatible-function-pointer-types-strict warning: a function
            stored in a slot whose type differs only by an enum against its
            underlying integer, which C accepts and kCFI hashes apart.

A function pointer laundered through NvP64 or void * is invisible to all of them:
only a boot on the hardware with cfi=warn finds those.

Usage: kcfi_check.py SRC LOG...
  SRC  the open-gpu-kernel-modules tree, patched
  LOG  the output of the RM and the Kbuild builds, with both warnings
"""

import pathlib
import re
import sys

EXPORT = ("NV_STATUS (*)(void *, void *)", "NV_STATUS (*)(void *)")
# (file, from, to): casts that never reach a call with the wrong type.
ALLOWED_CASTS = [
    # Exported-method tables store every entry as void (*)(void) ...
    (r"generated/g_\w+_nvoc\.c", EXPORT, ("void (*)(void)",)),
    # ... and these callers cast it back by paramSize, which `exports` verifies.
    (
        r"src/libraries/resserv/src/rs_resource\.c|src/kernel/gpu/deferred_api\.c",
        ("void (*)(void)",),
        ("CONTROL_EXPORT_FNPTR", "CONTROL_EXPORT_FNPTR_NO_PARAMS"),
    ),
    (r"src/kernel/gpu/gpu\.c", ("void (*)(void)",), EXPORT),
    # The timer wrapper parks the inner callback in the TIMEPROC slot while it runs
    # and calls it only through its own type.
    (
        r"src/kernel/gpu/timer/timer\.c",
        ("TIMEPROC", "TMR_CALLBACK_FUNCTION"),
        ("TIMEPROC", "TMR_CALLBACK_FUNCTION"),
    ),
]
ENUM = re.compile(
    r"(?P<file>\S+?):\d+:\d+: warning: (?P<msg>incompatible function pointer types.*?)"
    r" \[-Wincompatible-function-pointer-types-strict\]"
)
CAST = re.compile(
    r"(?P<file>\S+?):\d+:\d+: warning: cast from '(?P<src>[^']*)'(?: \(aka '[^']*'\))?"
    r" to '(?P<dst>[^']*)'(?: \(aka '[^']*'\))? converts to incompatible function type"
)


def params(text):
    """The parameter types of a C parameter list, without names, `struct` or comments."""
    text = re.sub(r"/\*.*?\*/", "", text)
    return [re.sub(r"\bstruct\s+|\s+\w+$|\s", "", p.strip()) for p in text.split(",")]


def bindata(generated):
    headers = "".join(
        p.read_text(errors="replace") for p in generated.glob("g_*_nvoc.h")
    )
    found = []
    for path in sorted(generated.glob("g_bindata_*.c")):
        for m in re.finditer(
            r"^(?:const\s+)?BINDATA_ARCHIVE\s*\*\s*(\w+)\s*\(([^)]*)\)\s*\{",
            path.read_text(errors="replace"),
            re.M,
        ):
            name, defined = m.groups()
            decl = re.search(
                r"BINDATA_ARCHIVE\s*\*\s*" + name + r"\s*\(([^)]*)\)\s*;", headers
            )
            if decl is None:
                found.append(f"bindata: {name} has no declaration in the NVOC headers")
            elif params(defined) != params(decl.group(1)):
                found.append(
                    f"bindata: {name} defined ({defined}) but declared ({decl.group(1)})"
                )
    return sorted(set(found))


def exports(generated):
    found = []
    for path in sorted(generated.glob("g_*_nvoc.c")):
        text = path.read_text(errors="replace")
        arity = {
            m.group(1): len(params(m.group(2)))
            for m in re.finditer(r"NV_STATUS (\w+__EXPORT)\(([^)]*)\)", text)
        }
        for m in re.finditer(
            r"\(void \(\*\)\(void\)\) &(\w+__EXPORT),.*?/\*paramSize=\*/\s*([^,]+),",
            text,
            re.S,
        ):
            expected = 1 if re.sub(r"/\*.*?\*/", "", m.group(2)).strip() == "0" else 2
            if arity.get(m.group(1)) != expected:
                found.append(
                    f"exports: {path.name} {m.group(1)} takes {arity.get(m.group(1))} arguments, paramSize wants {expected}"
                )
    return found


def casts(log):
    found, exceptions = [], 0
    for m in CAST.finditer(log):
        file = m.group("file").split("src/nvidia/")[-1]
        if any(
            re.fullmatch(f, file) and m.group("src") in s and m.group("dst") in d
            for f, s, d in ALLOWED_CASTS
        ):
            exceptions += 1
        else:
            found.append(f"casts: {file}: {m.group('src')} -> {m.group('dst')}")
    for m in ENUM.finditer(log):
        msg = re.sub(r" \(aka '[^']*'\)", "", m.group("msg"))
        found.append(f"enums: {m.group('file').split('/src/')[-1]}: {msg}")
    # The exported-method tables always warn: silence means the flags were lost.
    if exceptions == 0:
        found.append(
            "casts: no -Wcast-function-type-strict warning in the log, the flag did not reach the RM build"
        )
    return sorted(set(found))


def main(argv):
    if len(argv) < 3:
        print("usage: kcfi_check.py SRC LOG...", file=sys.stderr)
        return 2
    generated = pathlib.Path(argv[1]) / "src/nvidia/generated"
    problems = (
        bindata(generated)
        + exports(generated)
        + casts("".join(pathlib.Path(a).read_text(errors="replace") for a in argv[2:]))
    )
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"kcfi_check: {len(problems)} kCFI type mismatches", file=sys.stderr)
        return 1
    print("kcfi_check: bindata getters, exported methods, function casts and enum slots consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
