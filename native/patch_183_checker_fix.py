"""Re-apply the content-checker edits for §181/§182/§183 after the file was truncated to 0 bytes.

The bug that caused it, written down because it will happen again: `open(path, "w")` **truncates
immediately**, so a script that dies between `open` and `write` leaves an empty file -- and the
traceback only mentions the `write` call, not the damage. Every editor script in this repo must build
the whole string **before** opening the file for writing.
"""
import io

PATH = "native/sts_content_check.py"
CARDS = ["bandage_up", "blind", "dark_shackles"]


def edit(text, old, new, why):
    assert text.count(old) == 1, (why, text.count(old), old[:60])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert len(text) > 1000, "the file is empty again -- restore it from git first"

    # ---- §181: a new status row and its consumption -------------------------------------
    text = edit(
        text,
        '''    # §180: +1 -- `standard.fairy_in_a_bottle`, the first row that uses `DeathPrevention`.
    "statuses": 26,''',
        '''    # §180: +1 -- `standard.fairy_in_a_bottle`, the first row that uses `DeathPrevention`.
    # §181: +1 -- `standard.duplication`, the first `UsesCharges` status the kernel consumes.
    "statuses": 27,''',
        "§181 status count",
    )
    text = edit(
        text,
        '''    "standard.fairy_in_a_bottle": [],''',
        '''    "standard.fairy_in_a_bottle": [],
    # §181: no triggers and no modifiers -- `play.rs` reads its charges when a card program is about
    # to start ("your next card is played twice"). An empty list here is an **assertion**.
    "standard.duplication": [],''',
        "§181 status inventory",
    )

    # ---- §182: the auto-play atom --------------------------------------------------------
    text = edit(
        text,
        '''                "combat_upgrade_hand", "combat_randomize_costs", "combat_flee",''',
        '''                "combat_upgrade_hand", "combat_randomize_costs", "combat_flee",
                # §182: auto-play reads the count, so it is **not** in `NO_AMOUNT`.
                "combat_autoplay_top",''',
        "§182 atom",
    )

    # ---- §183: three colorless cards + the potion ---------------------------------------
    text = edit(
        text,
        '"cards": 38,',
        '"cards": 41,',
        "§183 card count",
    )
    text = edit(
        text,
        '''NOT_UPGRADABLE_TAGS = ("curse", "status")''',
        '''# §183: `colorless` joins the list, and the reason is **not** "they cannot be upgraded" (in StS
# they can) -- it is that **no deck can ever hold them**: the only way a colorless card enters play is
# a potion's offer, inside one fight. A `+` row for them would be content nothing can reach, and
# inventing three upgrades whose wiki numbers nobody read is worse than saying so.
NOT_UPGRADABLE_TAGS = ("curse", "status", "colorless")''',
        "§183 upgradable tags",
    )
    with io.open(PATH, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print("checker edits re-applied")


if __name__ == "__main__":
    main()
