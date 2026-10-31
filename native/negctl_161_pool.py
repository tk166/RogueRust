"""§161.1 negative control: delete the `pool_fits` guard from one reader and check the test goes RED.

`python native/negctl_161_pool.py` / `--restore`.
"""
import io
import sys

PATH = "kernel/rd-run/src/state.rs"

GUARD = """        Self::pool_fits(card_pool.len())?;
        for index in 0..card_pool.len() {"""

BROKEN = """        for index in 0..card_pool.len() {"""

# The old shape also cut the loop, so restore **that** too -- otherwise the guard-less version would
# index past the array and panic instead of quietly drawing from a shorter pool.
BROKEN_WITH_CUT = """        for index in 0..card_pool.len().min(MAX_POOL) {"""


def main():
    restore = "--restore" in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if restore:
        assert text.count(BROKEN_WITH_CUT) == 1, text.count(BROKEN_WITH_CUT)
        text = text.replace(BROKEN_WITH_CUT, GUARD)
    else:
        assert text.count(GUARD) == 1, text.count(GUARD)
        text = text.replace(GUARD, BROKEN_WITH_CUT)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("roll_reward guard", "restored" if restore else "removed + re-cut")


if __name__ == "__main__":
    main()
