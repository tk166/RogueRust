"""rd-core's `the_potions_are_readable`: §161.5 moves the count, the bands, the vocabulary."""
import io

PATH = "kernel/rd-core/src/content.rs"


def main():
    t = io.open(PATH, encoding="utf-8").read()

    def sub(old, new):
        nonlocal t
        assert t.count(old) == 1, (t.count(old), old[:60])
        t = t.replace(old, new)

    sub(
        "            23,\n"
        '            "\u00a7158: eleven after \u00a7157, plus nine that need no new mechanic, plus the three whose \\\n'
        "             effect is a card choice (\u00a7161.3 and \u00a7161.4)\"",
        "            25,\n"
        '            "\u00a7158: eleven after \u00a7157, plus nine that need no new mechanic, plus the five whose \\\n'
        "             effect is a card choice (\u00a7161.3 / \u00a7161.4 / \u00a7161.5)\"",
    )

    sub(
        '                        "choice_discard_to_hand",\n'
        "                    ]\n"
        "                    .contains(kind),",
        '                        "choice_discard_to_hand",\n'
        "                        // \u00a7161.5: `choice_offered:<tag>` -- \u4e09\u5f20\u5019\u9009\uff0c"
        "payload \u662f**\u6807\u7b7e**\u3002\n"
        '                        "choice_offered",\n'
        "                    ]\n"
        "                    .contains(kind),",
    )

    sub(
        "                .all(|(kind, _)| matches!(\n"
        "                    *kind,\n"
        '                    "potion_fill"\n'
        '                        | "choice_hand_exhaust"\n'
        '                        | "choice_hand_discard_draw"\n'
        '                        | "choice_discard_to_hand"\n'
        "                ))",
        "                .all(|(kind, _)| matches!(\n"
        "                    *kind,\n"
        '                    "potion_fill"\n'
        '                        | "choice_hand_exhaust"\n'
        '                        | "choice_hand_discard_draw"\n'
        '                        | "choice_discard_to_hand"\n'
        '                        | "choice_offered"\n'
        "                ))",
    )

    sub("            [12, 7, 4],", "            [14, 7, 4],")

    # the sorted id list: two new Common potions
    sub('                "block_potion",', '                "attack_potion",\n                "block_potion",')
    sub('                "regen_potion",', '                "regen_potion",\n                "skill_potion",')

    # the comment above the band assertion
    sub(
        "        // **17 Common / 9 Uncommon / 7 Rare = 33**). Ten are still missing, and every one of them\n"
        "        // needs a mechanic the kernel does not have yet -- three card offers from the pool\n"
        "        // (Attack / Skill / Power), a colorless pool (Colorless Potion), a card upgrade in a fight\n"
        "        // (Blessing of the Forge), a **cost rewrite** (Snecko Oil), an auto-play or a duplicate\n"
        "        // play (Distilled Chaos, Duplication Potion), a death save (Fairy in a Bottle), a flee\n"
        '        // (Smoke Bomb). Pinning the band sizes is what makes "we are at 23" a fact',
        "        // **17 Common / 9 Uncommon / 7 Rare = 33**). Eight are still missing: Power Potion needs\n"
        "        // three `power`-tagged cards (this content has zero), Colorless Potion needs a colorless\n"
        "        // pool, Blessing of the Forge a card upgrade in a fight, Snecko Oil an **hand-wide** cost\n"
        "        // rewrite, Distilled Chaos / Duplication Potion an auto-play and a duplicate play, Fairy\n"
        "        // in a Bottle a death save, Smoke Bomb a flee. Pinning the band sizes is what makes\n"
        '        // "we are at 25" a fact',
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(t)
    print("content.rs: 25 potions")


if __name__ == "__main__":
    main()
