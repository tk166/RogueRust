"""§187 content gate: pin the 13 ascension variants and refuse a "variant that changes nothing".

Two invariants, neither of which the kernel tests can see:

1. **every variant is listed here** (a variant nobody pinned is a number nobody checked -- the same
   trap as §183's `DurationTurns`);
2. **`ProgramAsc`'s facts differ from `Program`'s** (an ascension that changes nothing is a typo with
   no symptom: the fight runs, the numbers look plausible, and the difficulty never moves).
"""
import io

PATH = "native/sts_content_check.py"

TABLE = '''
# \u00a7187\uff1a`EACT.ProgramAsc` \u7684**独立第二份**。每一行都是 wiki 的数字（出处列在
# `native/patch_187_content.py` \u7684\u8868\u5934\uff09\uff0c\u800c\u4e0d\u662f\u4ece\u5185\u5bb9\u62c4\u8fc7\u6765\u7684 --
# "\u4ece\u5185\u5bb9\u751f\u6210\u671f\u671b\u503c"\u7b49\u4e8e\u6ca1\u6709\u671f\u671b\u503c\u3002
INV_ASC_VARIANTS = {
    # action id: (AscensionMin, facts)
    "blue_slaver.stab": (2, [("damage", 13, "event")]),
    "blue_slaver.rake": (2, [("damage", 8, "event"), ("status", "standard.weak", 1, "event")]),
    "slaver_red.stab": (2, [("damage", 14, "event")]),
    "slaver_red.scrape": (2, [("damage", 9, "event"),
                             ("status", "standard.vulnerable", 1, "event")]),
    "lagavulin.attack": (3, [("damage", 20, "event")]),
    "book_of_stabbing.multi_stab": (3, [("repeat", ("expr", "add"), "damage", 7, "event"),
                                        ("counter", "book_stab_uses", 1, True, "source")]),
    "book_of_stabbing.big_stab": (3, [("damage", 24, "event")]),
    "taskmaster.scouring_whip": (3, [("damage", 7, "event"),
                                     ("card", "wound", 2, "DiscardPile", "event")]),
    "nemesis.tri_attack": (4, [("damage", 7, "event"), ("damage", 7, "event"),
                               ("damage", 7, "event")]),
    "nemesis.tri_burn": (19, [("card", "burn", 5, "DiscardPile", "event")]),
    "reptomancer.spawn_dagger": (19, [("spawn", "dagger", 22), ("spawn", "dagger", 22)]),
    "reptomancer.big_bite": (4, [("damage", 34, "event")]),
    "reptomancer.snake_strike": (4, [("damage", 16, "event"), ("damage", 16, "event"),
                                     ("status", "standard.weak", 1, "event")]),
}


def check_ascension_variants(doc):
    """\u00a7187\uff1a**每一条**升档节目都必须被上面那张表钉住\uff0c\u4e14\u4e0e\u57fa\u7840\u8282\u76ee**\u4e0d\u540c**\u3002"""
    print("[7] ascension variants (port-plan.md \u00a7187)")
    actions = {a["Id"]: a for a in doc.get("EnemyActions") or []}
    for aid, (threshold, facts) in INV_ASC_VARIANTS.items():
        action = actions.get(aid)
        if action is None:
            fail("asc." + aid, "action missing")
            continue
        if "ProgramAsc" not in action:
            fail("asc." + aid, "no ProgramAsc")
            continue
        if action.get("AscensionMin") != threshold:
            fail("asc." + aid, "AscensionMin %r, inv says %r"
                 % (action.get("AscensionMin"), threshold))
        got = program_facts(action["ProgramAsc"]["Root"])
        if got != facts:
            fail("asc." + aid, "facts %s, inv says %s" % (got, facts))
        # \u4e00\u4e2a"\u53d8\u4f53"\u5982\u679c\u4e0e\u57fa\u7840\u4e00\u6a21\u4e00\u6837\uff0c\u5b83\u5c31\u662f\u4e00\u4e2a**\u6ca1\u6709\u75c7\u72b6\u7684\u9519\u5b57**\uff1a
        # \u6218\u6597\u7167\u8dd1\u3001\u6570\u5b57\u770b\u8d77\u6765\u5408\u7406\uff0c\u800c\u96be\u5ea6\u4ece\u6765\u6ca1\u52a8\u8fc7\u3002
        if got == program_facts(action["Program"]["Root"]):
            fail("asc." + aid, "variant facts equal the base -- this ascension does nothing")
    # \u53cd\u5411\uff1a\u5185\u5bb9\u91cc\u6709\u800c\u8868\u91cc\u6ca1\u6709\u7684\u53d8\u4f53\u4e5f\u4e0d\u884c\uff08"\u6ca1\u4eba\u9489\u8fc7\u7684\u6570\u5b57"\uff09\u3002
    unknown = sorted(aid for aid, action in actions.items()
                     if "ProgramAsc" in action and aid not in INV_ASC_VARIANTS)
    if unknown:
        fail("asc.unknown", "variants not pinned by the inventory: %s" % unknown)
    ok("ascension variants", "%d variants pinned (A2/A3/A4 + A17-A19)" % len(INV_ASC_VARIANTS))
'''

ANCHOR = '''def check_statuses(doc):'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert "INV_ASC_VARIANTS" not in text, "already patched"
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    text = text.replace(ANCHOR, TABLE.lstrip("\n") + "\n" + ANCHOR)
    # call it from the actions section (after the per-action inventory check)
    call_anchor = '''    ok("enemy actions", "%d actions x (intent, facts)" % len(INV_ACTIONS))'''
    assert text.count(call_anchor) == 1
    text = text.replace(call_anchor, call_anchor + "\n    check_ascension_variants(doc)")
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("checker: ascension variants pinned")


if __name__ == "__main__":
    main()
