"""§161.4 negative control. `python native/negctl_164.py price [--restore]`.

Breaks the one thing §161.4 adds to `play.rs`: the price is zeroed after the play is paid for.
`the_per_copy_price_is_consumed_by_the_play` must then go red on the *second* play (it stays free).
"""
import io
import sys

PLAY = "kernel/rd-core/src/play.rs"

OK = """    if let Some((_, slot)) = find_card_slot(state, &plan.source, &plan.instance) {
        if let Some(card) = state.card_mut(slot) {
            if mark_counter(card, CARD_COST_DELTA_COUNTER) != 0 {
                if let Ok(key) = CounterId::new(CARD_COST_DELTA_COUNTER) {
                    card.set_mark_counter(key, 0)?;
                }
            }
        }
    }"""

BROKEN = """    // BROKEN CONTROL: the price is never spent, so it becomes a standing discount.
    """

# ---- display -----------------------------------------------------------------------------------
# The screen's cost column is a **second** pricing: drop the delta from it and the page shows the
# printed 1 while the kernel charges 0. The browser gate must catch it (`lmFreeShown`).
LIB = "kernel/rd-wasm/src/lib.rs"

SHOWN_OK = """            if cost > 0 {
                if let Ok(key) = rd_core::state::CounterId::new(
                    rd_core::state::CARD_COST_DELTA_COUNTER,
                ) {
                    let delta = instance
                        .mark_counters()
                        .iter()
                        .find(|counter| counter.key == key)
                        .map_or(0, |counter| counter.value);
                    if delta != 0 {
                        cost = (cost + delta).max(0);
                    }
                }
            }"""
SHOWN_BROKEN = """            // BROKEN CONTROL: the screen shows the printed price while the kernel charges less."""


def patch(path, ok, broken, restore):
    text = io.open(path, encoding="utf-8").read()
    a, b = (broken, ok) if restore else (ok, broken)
    assert text.count(a) == 1, (path, text.count(a))
    io.open(path, "w", encoding="utf-8", newline="").write(text.replace(a, b))


def main():
    which = sys.argv[1]
    restore = "--restore" in sys.argv
    if which == "price":
        patch(PLAY, OK, BROKEN, restore)
    elif which == "display":
        patch(LIB, SHOWN_OK, SHOWN_BROKEN, restore)
    else:
        raise SystemExit(f"unknown control {which!r}")
    print(f"{which}: {'restored' if restore else 'broken'}")


if __name__ == "__main__":
    main()
