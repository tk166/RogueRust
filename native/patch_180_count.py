"""§180: the potion count moved 29 -> 30 (Fairy in a Bottle), and it is a Rare."""
import io

PATH = "kernel/rd-core/src/content.rs"
BACKSLASH = chr(92)

with io.open(PATH, encoding="utf-8") as handle:
    lines = handle.read().split("\n")

index = None
for i, line in enumerate(lines):
    if line.strip() == "content.potion_count()," and lines[i + 1].strip() == "29,":
        index = i
        break
assert index is not None, "the potion-count assertion moved"

# The message is a three-line continuation; rewrite it whole so the number and the story agree.
message_lines = [
    '            "§158: eleven after §157, plus nine that need no new mechanic, plus the five whose ' + BACKSLASH,
    "             effect is a card choice, plus §161.7's Power Potion, plus §179's three (Blessing " + BACKSLASH,
    "             of the Forge, Snecko Oil, Smoke Bomb), plus §180's Fairy in a Bottle\"",
]
lines[index + 1] = "            30,"
lines[index + 2:index + 5] = message_lines

text = "\n".join(lines)
# The id list is sorted; insert in place.
assert '"fairy_in_a_bottle",' not in text
text = text.replace(
    '                "explosive_potion",\n                "fear_potion",',
    '                "explosive_potion",\n                "fairy_in_a_bottle",\n                "fear_potion",',
)
# Rare gains one (Fairy is Rare) => [16, 7, 6] -> [16, 7, 7].
assert "            [16, 7, 6]," in text
text = text.replace("            [16, 7, 6],", "            [16, 7, 7],")

with io.open(PATH, "w", encoding="utf-8", newline="") as handle:
    handle.write(text)
print("potions 29 -> 30, ids + bands updated")
