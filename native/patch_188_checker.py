"""§188 gate: the event vocabulary now checks **lists**, and refuses three shapes.

The old check read `Effect0` / `Effect1` (one word per option). The list shape makes three new
failures possible, and each of them is silent without a check:

1. an effect **outside the closed vocabulary** (the run layer would refuse the click and leave a dead
   button -- this is the failure §143 built the check for);
2. an `A15` list that **equals the base list** -- "events are worse" that changes nothing is a typo
   with no symptom (same rule as §187's ascension variants);
3. **two deck edits** in one option -- `remove_card` + `upgrade_card` cannot both become the single
   pending pick, so one of them would be dropped (`RunError::TwoDeckChanges` at runtime).
"""
import io

PATH = "native/sts_content_check.py"

OLD_START = """def check_event_vocabulary(doc):
    print("[6c] event vocabulary (port-plan.md §143)")"""

NEW = '''EVENT_DECK_EDITS = ("remove_card", "upgrade_card", "transform_card")


def check_event_vocabulary(doc):
    """\u00a7143 + \u00a7188\uff1a\u6bcf\u4e2a\u9009\u9879\u662f\u4e00\u4e2a**\u6548\u679c\u5217\u8868**\uff0c\u6bcf\u4e2a\u6548\u679c\u90fd\u5728\u95ed\u8bcd\u8868\u91cc\u3002

    \u4e09\u6761\u5224\u636e\uff08\u6bcf\u4e00\u6761\u5bf9\u5e94\u4e00\u79cd\u6ca1\u6709\u75c7\u72b6\u7684\u9519\u8bef\uff09\uff1a
    * \u8bcd\u8868\u5916\u7684\u6548\u679c \u21d2 \u4e0b\u9762\u7684 `fail`\uff08\u70b9\u4e0b\u53bb\u4e00\u4e2a\u6b7b\u6309\u94ae\uff09\uff1b
    * `Effects*Asc` \u4e0e\u57fa\u7840**\u4e00\u6a21\u4e00\u6837** \u21d2 "A15 \u53d8\u7cdf"\u4ec0\u4e48\u90fd\u6ca1\u53d8\uff1b
    * \u4e00\u4e2a\u9009\u9879\u91cc**\u4e24\u4e2a\u6539\u724c\u6548\u679c** \u21d2 \u5f85\u7b54\u7684\u9009\u724c\u53ea\u6709\u4e00\u4e2a\u4f4d\u7f6e\uff0c\u4e00\u5b9a\u4e22\u4e00\u4e2a\u3002
    """
    print("[6c] event vocabulary (port-plan.md \u00a7143 / \u00a7188)")
    rooms = doc.get("UnknownRooms") or []
    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    relics = {r["Id"] for r in doc.get("Relics") or []}
    counts = {"bare": 0, "curse": 0, "relic": 0, "effects": 0, "asc": 0}
    for room in rooms:
        for slot in ("0", "1"):
            base = room.get("Effects" + slot) or []
            asc = room.get("Effects" + slot + "Asc") or []
            label = "UnknownRooms.%s.Effects%s" % (room.get("Id"), slot)
            if not isinstance(base, list):
                fail(label, "not a list: %r" % (base,))
                continue
            if len(base) > 4 or len(asc) > 4:
                fail(label, "more than 4 effects (the kernel's MAX_EVENT_EFFECTS)")
            for kind_label, effects in (("", base), ("Asc", asc)):
                edits = 0
                for entry in effects:
                    effect = entry.get("Effect")
                    where = "%s%s.%s" % (label, kind_label, effect)
                    if not isinstance(effect, str):
                        fail(where, "Effect is not a string: %r" % (effect,))
                        continue
                    counts["effects"] += 1
                    if kind_label:
                        counts["asc"] += 1
                    if effect in EVENT_BARE_EFFECTS:
                        counts["bare"] += 1
                        continue
                    kind, _, payload = effect.partition(":")
                    if kind == "curse" and payload:
                        counts["curse"] += 1
                        if payload not in cards:
                            fail(where, "curse:%s \u4e0d\u662f\u5185\u5bb9\u91cc\u7684\u5361" % payload)
                        elif cards[payload] != "Curse":
                            fail(where, "curse:%s \u7684 Rarity \u662f %s\uff0c\u4e0d\u662f Curse"
                                 % (payload, cards[payload]))
                        continue
                    if kind == "relic" and payload:
                        counts["relic"] += 1
                        if payload not in relics:
                            fail(where, "relic:%s \u4e0d\u5728 Relics \u8868\u91cc" % payload)
                        elif payload not in IMPLEMENTED_RELICS:
                            fail(where, "relic:%s \u7684\u6548\u679c\u5185\u6838\u6ca1\u5b9e\u73b0\uff08%s\uff09"
                                 % (payload, " / ".join(IMPLEMENTED_RELICS)))
                        continue
                    fail(where, "\u8bcd\u8868\u5916\u7684\u6548\u679c %r" % (effect,))
                edits = sum(1 for e in effects if e.get("Effect") in EVENT_DECK_EDITS)
                if edits > 1:
                    fail(label + kind_label,
                         "%d \u4e2a\u6539\u724c\u6548\u679c\uff08\u5f85\u7b54\u9009\u724c\u53ea\u6709\u4e00\u4e2a\u4f4d\u7f6e\uff09" % edits)
            # \u00a7188\uff1aA15 \u7684\u53d8\u4f53\u5fc5\u987b**\u771f\u7684\u4e0d\u4e00\u6837**\u3002
            if asc and asc == base:
                fail(label + "Asc", "the A15 list equals the base -- this ascension does nothing")
    ok("event effects",
       "%d rooms, %d effect(s) (%d in A15 lists), %d bare / %d curse: / %d relic:"
       % (len(rooms), counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"]))'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    if "EVENT_DECK_EDITS" in text:
        print("already patched")
        return
    start = text.index(OLD_START)
    # the function ends at the `ok("event effects", ..)` call's closing paren
    marker = '''    ok("event effects", "%d rooms, %d bare / %d curse: / %d relic:"
       % (len(rooms), counts["bare"], counts["curse"], counts["relic"]))'''
    assert text.count(marker) == 1
    end = text.index(marker) + len(marker)
    text = text[:start] + NEW + text[end:]
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("checker rewritten for effect lists")


if __name__ == "__main__":
    main()
