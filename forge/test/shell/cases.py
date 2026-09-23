#!/usr/bin/python3
"""The surface cases of doc_shell.md, SH13: scale {1.0, 1.5} x theme {light, dark} x
text {English, German for length, a right-to-left pseudo-locale}.

    cases.py <surface>      one case per line: tag, variant, scale, locale, catalog (tab-separated)
"""
import sys
from collections import namedtuple
from itertools import product

Case = namedtuple("Case", "tag variant scale locale catalog")

# short name -> (LC_ALL, catalog handed to ATHANOR_I18N_CATALOG). Our own strings come
# from the catalog file, read by athanor-i18n, whatever the process locale is; LC_ALL
# gives the case its date and GTK's own strings. English is the message ids: no catalog.
# German and the right-to-left pseudo-language are catalogs of the test; the product
# ships it and en. The pseudo-language declares "Language: ar", which is what makes the
# greeter mirror.
LOCALES = {"en": ("en_US.UTF-8", "-"), "de": ("de_DE.UTF-8", "de.mo"), "rtl": ("ar_EG.UTF-8", "rtl.mo")}
SURFACES = {"greeter": {"variants": ("light", "dark"), "scales": ("1.0", "1.5")}}


def surface_cases(surface):
    spec = SURFACES[surface]
    return [Case(f"{surface}-{variant}-{scale}-{short}", variant, scale, locale, catalog)
            for variant, scale, (short, (locale, catalog)) in product(spec["variants"], spec["scales"], LOCALES.items())]


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SURFACES:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    for case in surface_cases(sys.argv[1]):
        print("\t".join(case))
