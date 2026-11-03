"""§179: the potion count moved 26 -> 29, so the assertion that pins it must move too."""
import io

PATH = "kernel/rd-core/src/content.rs"

with io.open(PATH, encoding="utf-8") as handle:
    lines = handle.read().split("\n")

# The block is:
#     assert_eq!(
#         content.potion_count(),
#         26,
#         "§158: ... whose \
#          effect is a card choice, plus §161.7's Power Potion"
#     );
index = None
for i, line in enumerate(lines):
    if line.strip() == "content.potion_count()," and lines[i + 1].strip() == "26,":
        index = i
        break
assert index is not None, "the potion count assertion moved"

BACKSLASH = chr(92)
lines[index + 1] = "            29,"
lines[index + 2] = (
    '            "§158: eleven after §157, plus nine that need no new mechanic, plus the five whose '
    + BACKSLASH
)
lines[index + 3] = (
    "             effect is a card choice, plus §161.7's Power Potion, plus §179's three (Blessing "
    + BACKSLASH
)
lines.insert(
    index + 4,
    '             of the Forge, Snecko Oil, Smoke Bomb)"',
)

with io.open(PATH, "w", encoding="utf-8", newline="") as handle:
    handle.write("\n".join(lines))
print("\n".join(lines[index:index + 7]))
