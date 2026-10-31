"""§161.4 content: Liquid Memories (Uncommon), plus the two gates' vocabularies.

Wiki: "Choose a card in your discard pile and return it to your hand. It costs 0 this turn."
Uncommon, shared -- the same two independent sources §161.3 used (`Potions` table +
`Module:Potions/data`).
"""
import io

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"
CHECK = "native/sts_content_check.py"
RUN = "kernel/rd-wasm/src/run.rs"
CONTENT_TEST = "kernel/rd-core/src/content.rs"


def sub(path, text, old, new):
    assert text.count(old) == 1, (path, text.count(old), old[:70])
    return text.replace(old, new)


def main():
    package = io.open(PACKAGE, encoding="utf-8").read()
    package = sub(
        PACKAGE,
        package,
        """      "Effect": "choice_hand_discard_draw",
      "Amount": 0,
      "Rarity": "Uncommon"
    }
  ],""",
        """      "Effect": "choice_hand_discard_draw",
      "Amount": 0,
      "Rarity": "Uncommon"
    },
    {
      "Id": "liquid_memories",
      "NameKey": "Liquid Memories",
      "DescriptionKey": "Choose a card in your discard pile and return it to your hand. It costs 0 this turn.",
      "Effect": "choice_discard_to_hand",
      "Amount": 0,
      "Rarity": "Uncommon"
    }
  ],""",
    )
    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(package)

    check = io.open(CHECK, encoding="utf-8").read()
    check = sub(
        CHECK,
        check,
        """POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw")""",
        """POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw",
                       "choice_discard_to_hand")""",
    )
    io.open(CHECK, "w", encoding="utf-8", newline="").write(check)

    run = io.open(RUN, encoding="utf-8").read()
    run = sub(
        RUN,
        run,
        """                    | "choice_hand_exhaust"
                    | "choice_hand_discard_draw"
            )""",
        """                    | "choice_hand_exhaust"
                    | "choice_hand_discard_draw"
                    | "choice_discard_to_hand"
            )""",
    )
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)

    # the rd-core content test: count, vocabulary, the sorted id list, the band split
    test = io.open(CONTENT_TEST, encoding="utf-8").read()
    test = sub(
        CONTENT_TEST,
        test,
        """            22,
            "§158: eleven after §157, plus nine that need no new mechanic, plus §161.3's two \\
             whose effect is a card choice\"""",
        """            23,
            "§158: eleven after §157, plus nine that need no new mechanic, plus the three whose \\
             effect is a card choice (§161.3, §161.4)\"""",
    )
    test = sub(
        CONTENT_TEST,
        test,
        """                        "choice_hand_exhaust",
                        "choice_hand_discard_draw",
                    ]
                    .contains(kind),""",
        """                        "choice_hand_exhaust",
                        "choice_hand_discard_draw",
                        "choice_discard_to_hand",
                    ]
                    .contains(kind),""",
    )
    test = sub(
        CONTENT_TEST,
        test,
        """                .all(|(kind, _)| matches!(*kind, "potion_fill" | "choice_hand_exhaust" | "choice_hand_discard_draw"))""",
        """                .all(|(kind, _)| matches!(*kind, "potion_fill" | "choice_hand_exhaust" | "choice_hand_discard_draw" | "choice_discard_to_hand"))""",
    )
    test = sub(
        CONTENT_TEST,
        test,
        """                "liquid_bronze",""",
        """                "liquid_bronze",
                "liquid_memories",""",
    )
    test = sub(
        CONTENT_TEST,
        test,
        """            [12, 6, 4],""",
        """            [12, 7, 4],""",
    )
    test = sub(
        CONTENT_TEST,
        test,
        """"§158: the wiki's counts for the only character this content has (`Potions`, Ironclad only:
        // **17 Common / 9 Uncommon / 7 Rare = 33**). Eleven are still missing, and every one of
        // them needs a mechanic the kernel does not have yet -- three card offers from the pool
        // (Attack / Skill / Power), a colorless pool (Colorless Potion), a card upgrade in a fight
        // (Blessing of the Forge), a **per-copy price** (Liquid Memories, Snecko Oil), an auto-play
        // or a duplicate play (Distilled Chaos, Duplication Potion), a death save (Fairy in a
        // Bottle), a flee (Smoke Bomb). Pinning the band sizes is what makes "we are at 22" a fact
        // instead of an impression -- ⚠️ and it is the assertion that went red when §161.3 added
        // Elixir and Gambler's Brew, which is the whole reason it is a number here.""",
        """"§158: the wiki's counts for the only character this content has (`Potions`, Ironclad only:
        // **17 Common / 9 Uncommon / 7 Rare = 33**). Ten are still missing, and every one of them
        // needs a mechanic the kernel does not have yet -- three card offers from the pool
        // (Attack / Skill / Power), a colorless pool (Colorless Potion), a card upgrade in a fight
        // (Blessing of the Forge), a **cost rewrite** (Snecko Oil), an auto-play or a duplicate play
        // (Distilled Chaos, Duplication Potion), a death save (Fairy in a Bottle), a flee (Smoke
        // Bomb). Pinning the band sizes is what makes "we are at 23" a fact instead of an
        // impression -- ⚠️ and it is the assertion that went red when §161.3 added Elixir and
        // Gambler's Brew, which is the whole reason it is a number here.""",
    )
    io.open(CONTENT_TEST, "w", encoding="utf-8", newline="").write(test)
    print("liquid_memories added; three vocabularies widened")


if __name__ == "__main__":
    main()
