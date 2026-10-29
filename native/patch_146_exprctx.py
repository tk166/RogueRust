"""Insert `x_cost: 0,` into every `ExprContext { .. }` literal that does not have it (§146).

The field is a plain i32 whose natural default is 0, but Rust struct literals are exhaustive, so the
13 test fixtures need the line. A script rather than 13 hand edits: the failure mode of a hand edit
here is "one fixture silently keeps the old shape", which the compiler would catch anyway -- but a
script run once is cheaper to review.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_146_exprctx.py
"""

import io
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kernel", "rd-core", "src")
NEEDLE = "ExprContext {"

for name in ("expr.rs", "exec.rs", "play.rs"):
    path = os.path.join(ROOT, name)
    text = io.open(path, encoding="utf-8").read()
    out = []
    index = 0
    changed = 0
    while True:
        at = text.find(NEEDLE, index)
        if at < 0:
            out.append(text[index:])
            break
        head = at + len(NEEDLE)
        out.append(text[index:head])
        match = re.search(r"\n(\s*)event_flags: [^\n]*\n", text[head:head + 800])
        if not match:
            out.append(text[head:])
            break
        end = head + match.end()
        block = text[head:end]
        if "x_cost" in block:
            out.append(block)
        else:
            out.append(block + match.group(1) + "x_cost: 0,\n")
            changed += 1
        index = end
    io.open(path, "w", encoding="utf-8", newline="").write("".join(out))
    print("%-10s +%d" % (name, changed))
