"""The §161.3 debug potion grant, on both sides of the ABI.

`RD_DEBUG.givePotion(id)` exists for the same reason `startWithSeed` does: a checker must not have
to hope for a 40% drop of one specific potion out of twenty-two, and the card-choice picker is
reachable through exactly two of them.
"""
import io

PAGE = "web/index.html"
SMOKE = "web/smoke.mjs"

GIVE = """      // §161.3: put a potion on the belt by id (a `POT` row). **Debug surface only** -- the
      // reasoning is `rd_run_grant_potion`'s own doc. A checker that has to hope for a 40% drop of
      // Elixir (two of twenty-two potions) is not a checker.
      givePotion: (id) => {
        const bytes = new TextEncoder().encode(id);
        const ptr = ex.rd_env_scratch_buf();
        new Uint8Array(ex.memory.buffer, ptr, bytes.length).set(bytes);
        return ex.rd_run_grant_potion(ptr, bytes.length);
      },
"""


def main():
    text = io.open(PAGE, encoding="utf-8").read()
    assert "givePotion" not in text, "already inserted"
    anchor = "      settle: () => new Promise((resolve) => setTimeout(resolve, 0)),"
    assert text.count(anchor) == 1, text.count(anchor)
    text = text.replace(anchor, GIVE + anchor)
    io.open(PAGE, "w", encoding="utf-8", newline="").write(text)

    smoke = io.open(SMOKE, encoding="utf-8").read()
    anchor = '  "rd_env_choice_confirm","'
    assert smoke.count(anchor) == 1, smoke.count(anchor)
    assert "rd_run_grant_potion" not in smoke, "already inserted"
    smoke = smoke.replace(
        anchor,
        anchor
        + """
  // §161.3: the debug potion grant, used by `RD_DEBUG.givePotion` and by `browser_test`.
  "rd_run_grant_potion",""",
    )
    io.open(SMOKE, "w", encoding="utf-8", newline="").write(smoke)
    print("page: RD_DEBUG.givePotion + smoke REQUIRED")


if __name__ == "__main__":
    main()
