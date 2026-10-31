"""§160 negative controls: put each old shape back and check the new test goes RED.

Run `python native/negctl_160.py <which>` then `cargo test -p rd-run <name>`, then
`python native/negctl_160.py <which> --restore`.

which = shop   : deduct the gold before `push_card` (the P0) -> a_refused_purchase...
        feather: multiply before dividing (the P1)        -> the_eternal_feather...
"""
import io
import sys

PATH = "kernel/rd-run/src/state.rs"

OLD_SHOP = """        self.push_card(offer.id.as_str())?;
        self.adjust_gold(-offer.price);
        self.shop.cards[slot].price = -1;
        Ok(())"""
NEW_SHOP = """        self.push_card(offer.id.as_str())?;
        self.adjust_gold(-offer.price);
        self.shop.cards[slot].price = -1;
        Ok(())"""

GOOD_FEATHER = "bonus += amount * (i32::from(self.deck_len) / 5);"
BAD_FEATHER = "bonus += amount * i32::from(self.deck_len) / 5;"


def main():
    which = sys.argv[1]
    restore = "--restore" in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if which == "shop":
        good = """        self.push_card(offer.id.as_str())?;
        self.adjust_gold(-offer.price);"""
        bad = """        self.adjust_gold(-offer.price);
        self.push_card(offer.id.as_str())?;"""
        src, dst = (bad, good) if restore else (good, bad)
    elif which == "feather":
        src, dst = (BAD_FEATHER, GOOD_FEATHER) if restore else (GOOD_FEATHER, BAD_FEATHER)
    else:
        raise SystemExit("which = shop | feather")
    assert text.count(src) == 1, (which, text.count(src))
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(src, dst))
    print(which, "restored" if restore else "broken")


if __name__ == "__main__":
    main()
