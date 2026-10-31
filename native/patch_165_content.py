"""§161.5 content: Attack Potion + Skill Potion, and a gate that makes the tag/pool promise real.

Both are **Common** (wiki). Power Potion is deliberately **not** added: our content has zero
`power`-tagged cards, so it could not offer three. The gate below is what stops that from becoming
a silent "the potion does nothing": `choice_offered:<tag>` requires **≥ 3 cards** carrying `<tag>`.
"""
import io

PACKAGE = "tools/contentc/packages/sts/sts.roguedeck.json"
CHECK = "native/sts_content_check.py"


def sub(path, text, old, new):
    assert text.count(old) == 1, (path, text.count(old), old[:70])
    return text.replace(old, new)


def main():
    package = io.open(PACKAGE, encoding="utf-8").read()
    package = sub(
        PACKAGE,
        package,
        """      "Effect": "choice_discard_to_hand",
      "Amount": 0,
      "Rarity": "Uncommon"
    }
  ],""",
        """      "Effect": "choice_discard_to_hand",
      "Amount": 0,
      "Rarity": "Uncommon"
    },
    {
      "Id": "attack_potion",
      "NameKey": "Attack Potion",
      "DescriptionKey": "Choose 1 of 3 random Attack cards to add to your hand. It costs 0 this turn.",
      "Effect": "choice_offered:attack",
      "Amount": 0,
      "Rarity": "Common"
    },
    {
      "Id": "skill_potion",
      "NameKey": "Skill Potion",
      "DescriptionKey": "Choose 1 of 3 random Skill cards to add to your hand. It costs 0 this turn.",
      "Effect": "choice_offered:skill",
      "Amount": 0,
      "Rarity": "Common"
    }
  ],""",
    )
    io.open(PACKAGE, "w", encoding="utf-8", newline="").write(package)

    check = io.open(CHECK, encoding="utf-8").read()
    # the vocabulary: `choice_offered:<tag>` is a `kind:payload` atom like the status ones
    check = sub(
        CHECK,
        check,
        """POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw",
                       "choice_discard_to_hand")""",
        """POTION_CHOICE_KINDS = ("choice_hand_exhaust", "choice_hand_discard_draw",
                       "choice_discard_to_hand", "choice_offered")""",
    )
    # the payload rule: `choice_offered` carries a **tag**, not a status id
    check = sub(
        CHECK,
        check,
        """            if kind in POTION_KINDS:
                if payload:
                    fail(label, "`%s` takes no payload" % kind)""",
        """            if kind in POTION_KINDS:
                if payload and kind != "choice_offered":
                    fail(label, "`%s` takes no payload" % kind)
                if kind == "choice_offered":
                    # §161.5: the payload is a **tag**, and the promise is "three of them exist".
                    # 少于三张时这瓶药给不出它写的东西 —— 那正是一个安静的死按钮。
                    if payload not in tags:
                        fail(label, "`choice_offered` names tag %r, which no card carries"
                             % (payload,))
                    else:
                        carriers = sum(1 for card in doc.get("Cards") or []
                                       if any(t.get("value") == payload
                                              for t in card.get("Tags") or []))
                        if carriers < 3:
                            fail(label, "`choice_offered:%s` needs 3 cards carrying it, %d exist"
                                 % (payload, carriers))""",
    )
    # `tags` must be in scope where the potion loop reads it
    check = sub(
        CHECK,
        check,
        """    potions = doc.get("Potions") or []
    statuses = {status["Id"] for status in doc.get("Statuses") or []}""",
        """    potions = doc.get("Potions") or []
    statuses = {status["Id"] for status in doc.get("Statuses") or []}
    # §161.5: every tag any card carries -- `choice_offered:<tag>` payloads must be one of these.
    tags = {tag.get("value") for card in doc.get("Cards") or []
            for tag in card.get("Tags") or []}""",
    )
    # no-amount rule: `choice_offered` reads no amount either
    check = sub(
        CHECK,
        check,
        """        NO_AMOUNT = ("potion_fill",) + POTION_CHOICE_KINDS""",
        """        NO_AMOUNT = ("potion_fill",) + POTION_CHOICE_KINDS""",
    )
    io.open(CHECK, "w", encoding="utf-8", newline="").write(check)
    print("content: attack_potion + skill_potion; gate checks the tag's carrier count")


if __name__ == "__main__":
    main()
