"""§156: drop the leftover walk loop from the potion test (the helper replaced it)."""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    lines = handle.read().split("\n")

start = None
for index, line in enumerate(lines):
    if "Find a fight to use it in" in line:
        start = index
        break
if start is None:
    print("already removed")
else:
    end = None
    for index in range(start, len(lines)):
        if 'assert!(started, "never reached a fight to use the potion in");' in lines[index]:
            end = index
            break
    if end is None:
        raise SystemExit("assert line not found")
    del lines[start : end + 1]
    # drop the blank line the removal left behind, if any doubled up
    if start < len(lines) and lines[start].strip() == "" and lines[start - 1].strip() == "":
        del lines[start]
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    print("removed lines", start + 1, "..", end + 1)
