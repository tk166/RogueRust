"""§181: fix the two expected numbers in the duplication test (the mechanism already works)."""
import io

PATH = "kernel/rd-core/src/play.rs"

with io.open(PATH, encoding="utf-8") as handle:
    lines = handle.read().split("\n")

# First assertion: 20 - 12 = 8 (twice), not 14.
assert lines[2593].strip() == "14,", lines[2593]
lines[2593] = "            8,"
lines[2594] = (
    "            \"20 - 6 - 6: the program ran **twice**. 14 would mean once, and that is the shape "
    "a \\"
)
lines[2595] = "             'the status was there but nothing read it' regression takes.\""

# Second assertion: 8 - 6 = 2 after one more (unduplicated) Strike.
for i in range(2596, 2640):
    if lines[i].strip() == "8," and "enemy_a" in lines[i - 1]:
        lines[i] = "            2,"
        break
else:
    raise AssertionError("second assertion not found")

with io.open(PATH, "w", encoding="utf-8", newline="") as handle:
    handle.write("\n".join(lines))
print("done")
