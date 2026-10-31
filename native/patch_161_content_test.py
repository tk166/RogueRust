"""rd-core's `the_potions_are_readable`: the fourth copy of the potion vocabulary (and the one that
went red on `choice_hand_exhaust`, which is exactly what it is for).

It asserted 20 potions, a 12/4/4 band split, a sorted id list and the atom whitelist. §161.3 moves
all four; the IOU in its own comment ("thirteen are still missing, and every one of them needs an
in-fight card choice") is the part worth rewriting rather than editing.
"""
import io

PATH = "kernel/rd-core/src/content.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:60])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    text = sub(
        text,
        """        assert_eq!(
            content.potion_count(),
            20,
            "§158: eleven after §157, plus the nine that need no new mechanic"
        );""",
        """        assert_eq!(
            content.potion_count(),
            22,
            "§158: eleven after §157, plus nine that need no new mechanic, plus §161.3's two \\
             whose effect is a card choice"
        );""",
    )

    text = sub(
        text,
        """                        // §157: the effects about the **run** rather than the fight.
                        "max_hp",
                        "potion_fill",
                    ]
                    .contains(kind),""",
        """                        // §157: the effects about the **run** rather than the fight.
                        "max_hp",
                        "potion_fill",
                        // §161.3: the effects that are a **question** (`PendingChoice`). They
                        // read no amount and do not resolve inside `rd_env_use_potion`.
                        "choice_hand_exhaust",
                        "choice_hand_discard_draw",
                    ]
                    .contains(kind),""",
    )

    text = sub(
        text,
        """            // `potion_fill` is the only atom that reads no amount (it fills whatever is empty), so
            // the rule is per-atom rather than per-row: a flat "amount > 0" would have forced a
            // meaningless `1` into Entropic Brew's row and pinned nothing.
            if atoms.iter().all(|(kind, _)| *kind == "potion_fill") {""",
        """            // Two atoms read no amount: `potion_fill` fills whatever is empty, and the §161.3
            // choice atoms take the player's answer instead of a number. The rule is per-atom
            // rather than per-row: a flat "amount > 0" would have forced a meaningless `1` into
            // Entropic Brew's row and pinned nothing.
            if atoms
                .iter()
                .all(|(kind, _)| matches!(*kind, "potion_fill" | "choice_hand_exhaust" | "choice_hand_discard_draw"))
            {""",
    )

    text = sub(
        text,
        """                "dexterity_potion",
                "energy_potion",""",
        """                "dexterity_potion",
                "elixir",
                "energy_potion",""",
    )

    text = sub(
        text,
        """                "fruit_juice",
                "heart_of_iron",""",
        """                "fruit_juice",
                "gamblers_brew",
                "heart_of_iron",""",
    )

    text = sub(
        text,
        """        // §158: the wiki's counts for the only character this content has (`Potions`, Ironclad only:
        // **17 Common / 9 Uncommon / 7 Rare = 33**). Thirteen are still missing, and every one of
        // them needs a mechanic the kernel does not have yet -- an in-fight card choice (Attack /
        // Skill / Power / Colorless Potion), a card upgrade or multi-select in a fight (Blessing of
        // the Forge, Elixir, Gambler's Brew, Liquid Memories), an auto-play or a duplicate play
        // (Distilled Chaos, Duplication Potion), a cost rewrite (Snecko Oil), a death save (Fairy in
        // a Bottle), a flee (Smoke Bomb). Pinning the band sizes is what makes "we are at 20" a fact
        // instead of an impression.
        assert_eq!(
            bands,
            [12, 4, 4],
            "Common / Uncommon / Rare -- the wiki's Ironclad pool is 17 / 9 / 7"
        );""",
        """        // §158: the wiki's counts for the only character this content has (`Potions`, Ironclad only:
        // **17 Common / 9 Uncommon / 7 Rare = 33**). Eleven are still missing, and every one of
        // them needs a mechanic the kernel does not have yet -- three card offers from the pool
        // (Attack / Skill / Power), a colorless pool (Colorless Potion), a card upgrade in a fight
        // (Blessing of the Forge), a **per-copy price** (Liquid Memories, Snecko Oil), an auto-play
        // or a duplicate play (Distilled Chaos, Duplication Potion), a death save (Fairy in a
        // Bottle), a flee (Smoke Bomb). Pinning the band sizes is what makes "we are at 22" a fact
        // instead of an impression -- ⚠️ and it is the assertion that went red when §161.3 added
        // Elixir and Gambler's Brew, which is the whole reason it is a number here.
        assert_eq!(
            bands,
            [12, 6, 4],
            "Common / Uncommon / Rare -- the wiki's Ironclad pool is 17 / 9 / 7"
        );""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("content.rs: potion vocabulary + counts moved to 22")


if __name__ == "__main__":
    main()
