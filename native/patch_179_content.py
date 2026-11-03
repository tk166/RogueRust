"""§179 content half: the three potions, plus the run-layer branch for "fled".

Wiki (slaythespire.wiki.gg/wiki/Potions_List, read 2026-11-02; base values, no upgrades):

| Potion | Rarity | Effect |
|---|---|---|
| Blessing of the Forge | Common | Upgrade all cards in your hand for the rest of combat. |
| Snecko Oil | Rare | Draw 5 cards. Randomize the costs of all cards in your hand for the rest of the combat. |
| Smoke Bomb | Rare | Escape from a non-boss combat. Receive no rewards. |

`Snecko Oil` is **two** atoms: `combat_draw` (the `Amount` = 5) and `combat_randomize_costs`.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"
RUN = "kernel/rd-wasm/src/run.rs"

POTIONS = [
    {
        "Id": "blessing_of_the_forge",
        "NameKey": "Blessing of the Forge",
        "DescriptionKey": "Upgrade all cards in your hand for the rest of combat.",
        "Effect": "combat_upgrade_hand",
        "Amount": 0,
        "Rarity": "Common",
    },
    {
        "Id": "snecko_oil",
        "NameKey": "Snecko Oil",
        "DescriptionKey": "Draw 5 cards. Randomize the costs of all cards in your hand for the rest of combat.",
        # Two atoms, one amount: the draw reads it, the randomization does not (`0..=3` is the rule).
        "Effect": "combat_draw,combat_randomize_costs",
        "Amount": 5,
        "Rarity": "Rare",
    },
    {
        "Id": "smoke_bomb",
        "NameKey": "Smoke Bomb",
        "DescriptionKey": "Escape from a non-boss combat. Receive no rewards.",
        "Effect": "combat_flee",
        "Amount": 0,
        "Rarity": "Rare",
    },
]


def main():
    document = json.load(io.open(SRC, encoding="utf-8"))
    existing = {potion["Id"] for potion in document["Potions"]}
    added = [potion for potion in POTIONS if potion["Id"] not in existing]
    assert len(added) == len(POTIONS), "run twice? " + str([p["Id"] for p in added])
    document["Potions"].extend(POTIONS)
    with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("potions now:", len(document["Potions"]))

    # ---- run layer: `result == 3` is "fled" ------------------------------------------------
    text = io.open(RUN, encoding="utf-8").read()
    old = """    if result == 1 {
        // `Burning Blood` and friends (`inv:§2`), now with a call site."""
    new = """    if result == 3 {
        // §179: Smoke Bomb -- "Escape from a non-boss combat. **Receive no rewards.**" So: no
        // `end_of_combat` (no relics fire), no reward roll, no boss credit. The node still paid
        // (the escape happened there), which is the `mark_resolved()` below.
        //
        // It is deliberately **not** a fourth `CombatResult`: the kernel's three match the
        // reference byte for byte and `result=` is part of the golden hash.
        session.state.mark_resolved();
        return 3;
    }
    if result == 1 {
        // `Burning Blood` and friends (`inv:§2`), now with a call site."""
    assert text.count(old) == 1, text.count(old)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(old, new))
    print("apply_fight_outcome knows result == 3 (fled)")


if __name__ == "__main__":
    main()
