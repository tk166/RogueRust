"""Exact RAW-file byte attribution per top-level section.

The compact size of a section is not what it costs in the 7.91 MB file: pretty printing
costs more for deeply nested sections than for flat ones. This walks the actual text.
"""
import json, re, sys
from collections import Counter

path = (sys.argv[1] if len(sys.argv) > 1 else
        r"D:\Vibe\sts-tui\ref\RogueDeck-Core\src\RogueDeck.Sandbox.Run\SampleContent\bureaucrats.roguedeck.json")
raw = open(path, "r", encoding="utf-8").read()
n = len(raw)
out = []
a = out.append

a("file            : %s" % path)
a("characters      : %d" % n)
a("")

# Top-level object: scan for top-level keys and their value spans, brace-aware, string-aware.
i = raw.index("{") + 1
spans = []
keypat = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:')
while i < n:
    while i < n and raw[i] in " \t\r\n,":
        i += 1
    if i >= n or raw[i] == "}":
        break
    m = keypat.match(raw, i)
    if not m:
        a("!! parse stalled at %d: %r" % (i, raw[i:i + 40]))
        break
    key = m.group(1)
    i = m.end()
    start = i
    # scan the value
    depth = 0
    instr = False
    esc = False
    while i < n:
        c = raw[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif c == "," and depth == 0:
                break
        i += 1
    spans.append((key, start, i, raw[start:i]))
    while i < n and raw[i] in " \t\r\n,":
        i += 1

a("%-16s %11s %8s %9s %8s %9s %8s" % ("section", "raw bytes", "%file", "compact", "raw/cmp",
                                        "lines", "indent B"))
tot = 0
rows = []
for key, s, e, text in spans:
    try:
        val = json.loads(text)
        comp = len(json.dumps(val, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except Exception as ex:
        comp = -1
    indent = sum(1 for c in text if c in " \t\r\n")
    lines = text.count("\n")
    rows.append((e - s + len(key) + 3, key, e - s, comp, indent, lines))
    tot += e - s
for rb, key, vb, comp, indent, lines in sorted(rows, reverse=True):
    a("%-16s %11d %7.2f%% %9d %8s %9d %8.2f%%"
      % (key, rb, 100.0 * rb / n, comp,
         ("%.2f" % (vb / comp)) if comp > 0 else "-", lines, 100.0 * indent / max(1, vb)))
a("")
a("sum of value spans: %d of %d raw chars (rest = key names, commas, braces, indentation)" % (tot, n))
a("")
a("TOTAL indent/whitespace chars in file: %d (%.1f%%)"
  % (sum(1 for c in raw if c in " \t\r\n"), 100.0 * sum(1 for c in raw if c in " \t\r\n") / n))
a("TOTAL leading-space chars          : %d (%.1f%%)"
  % (sum(1 for c in raw if c == " "), 100.0 * raw.count(" ") / n))
a("newlines                           : %d" % raw.count("\n"))
a("")
# depth profile
depth = 0
instr = False
esc = False
maxd = 0
hist = Counter()
for c in raw:
    if instr:
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            instr = False
        continue
    if c == '"':
        instr = True
    elif c in "[{":
        depth += 1
        maxd = max(maxd, depth)
    elif c in "]}":
        hist[depth] += 1
        depth -= 1
a("max JSON nesting depth: %d" % maxd)
a("closing brackets by depth: %s"
  % ", ".join("d%d=%d" % kv for kv in sorted(hist.items())))
print("\n".join(out))
