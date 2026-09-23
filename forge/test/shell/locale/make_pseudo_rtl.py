#!/usr/bin/python3
"""make_pseudo_rtl.py <template.pot> <out.po>

A right-to-left pseudo-catalog: every message is its id between RIGHT-TO-LEFT OVERRIDE
and POP DIRECTIONAL FORMATTING, so the copy stays readable to whoever reviews a golden
while the text runs, and the layout mirrors, the way Arabic or Hebrew would.
A strftime format is left untranslated: the override would reverse the digits it
expands to, and the case's LC_ALL already gives the date its right-to-left form.
"""
import re
import sys

RLO, PDF = "\u202e", "\u202c"
HEADER = ('msgid ""\nmsgstr ""\n"Language: ar\\n"\n"MIME-Version: 1.0\\n"\n'
          '"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n\n')


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as template:
        ids = [m for m in re.findall(r'^msgid "(.+)"$', template.read(), re.MULTILINE) if not m.startswith("%")]
    with open(argv[1], "w", encoding="utf-8") as out:
        out.write(HEADER)
        out.writelines(f'msgid "{msgid}"\nmsgstr "{RLO}{msgid}{PDF}"\n\n' for msgid in ids)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
