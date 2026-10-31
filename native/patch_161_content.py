"""§161.3: add Elixir and Gambler's Brew to the content, plus the content gate's vocabulary.

Both are **Uncommon** (wiki: Elixir is Uncommon + Ironclad-only, Gambler's Brew is Uncommon), and
both are the first potions whose effect is a *question* rather than a number.
"""
import io

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"
CHECK = "native/sts_content_check.py"

OLD_TAIL = """      "Effect": "potion_fill",
      "Amount": 0,
      "Rarity": "Rare"
    }
  ],
  "EventTables": {"""

NEW_TAIL = """      "Effect": "potion_fill",
      "Amount": 0,
      "Rarity": "Rare"
    },
    {
      "Id": "elixir",
      "NameKey": "Elixir",
      "DescriptionKey": "Exhaust any number of cards in your hand.",
      "Effect": "choice_hand_exhaust",
      "Amount": 0,
      "Rarity": "Uncommon"
    },
    {
      "Id": "gamblers_brew",
      "NameKey": "Gambler's Brew",
      "DescriptionKey": "Discard any number of cards, then draw that many.",
      "Effect": "choice_hand_discard_draw",
      "Amount": 0,
      "Rarity": "Uncommon"
    }
  ],
  "EventTables": {"""

OLD_KINDS = """POTION_KINDS = ("combat_block", "combat_energy", "combat_heal_percent", "combat_draw",
                "combat_damage", "combat_damage_all",
                # §157/§158: the effects that are about the **run**, not the fight (Fruit Juice,
                # Entropic Brew). §158 made them usable **outside** a fight, which is what the wiki
                # says; before that the "no fight" check came first and refused them.
                "max_hp", "potion_fill")"""

NEW_KINDS = """# §161.3: the two atoms whose effect is a **question** (`PendingChoice`). They read no amount and
# they do not resolve inside `rd_env_use_potion` -- the ABI returns "pending" and the answer arrives
# through `rd_env_choice_confirm`.
POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw")
POTION_KINDS = ("combat_block", "combat_energy", "combat_heal_percent", "combat_draw",
                "combat_damage", "combat_damage_all",
                # §157/§158: the effects that are about the **run**, not the fight (Fruit Juice,
                # Entropic Brew). §158 made them usable **outside** a fight, which is what the wiki
                # says; before that the "no fight" check came first and refused them.
                "max_hp", "potion_fill") + POTION_CHOICE_KINDS"""

OLD_AMOUNT = """        # §158: `potion_fill` is the only atom that reads no amount, so the rule is per-atom.
        takes_amount = any(atom.partition(":")[0] != "potion_fill" for atom in atoms)
        if takes_amount:
            if not isinstance(amount, int) or amount <= 0:
                fail(label, "Amount must be a positive integer, got %r" % (amount,))
        elif amount != 0:
            fail(label, "`potion_fill` reads no amount, so it must be 0, got %r" % (amount,))"""

NEW_AMOUNT = """        # §158: the rule is per-atom, because not every atom reads an amount.
        # §161.3 added the choice atoms, which read none either (the number of cards is the
        # player's answer, not a constant in the content).
        NO_AMOUNT = ("potion_fill",) + POTION_CHOICE_KINDS
        takes_amount = any(atom.partition(":")[0] not in NO_AMOUNT for atom in atoms)
        if takes_amount:
            if not isinstance(amount, int) or amount <= 0:
                fail(label, "Amount must be a positive integer, got %r" % (amount,))
        elif amount != 0:
            fail(label, "`%s` reads no amount, so it must be 0, got %r"
                 % (atoms[0].partition(":")[0], amount,))"""


def main():
    package = io.open(PACKAGE, encoding="utf-8").read()
    assert package.count(OLD_TAIL) == 1, package.count(OLD_TAIL)
    assert '"Id": "elixir"' not in package, "already added"
    package = package.replace(OLD_TAIL, NEW_TAIL)
    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(package)

    check = io.open(CHECK, encoding="utf-8").read()
    assert check.count(OLD_KINDS) == 1, check.count(OLD_KINDS)
    check = check.replace(OLD_KINDS, NEW_KINDS)
    assert check.count(OLD_AMOUNT) == 1, check.count(OLD_AMOUNT)
    check = check.replace(OLD_AMOUNT, NEW_AMOUNT)
    io.open(CHECK, "w", encoding="utf-8", newline="").write(check)
    print("content: elixir + gamblers_brew; gate vocabulary widened")


if __name__ == "__main__":
    main()
