"""§278：内容门 `check_event_vocabulary` 升级到**节点表**。

旧的判据按 `UnknownRooms[i].Effects{0,1}` 遍历 —— 事件变成树之后，那些格没了，于是
它**一条都不会检查**，而 `ok("event effects", "0 rooms...")` 仍然报绿。新判据按
`EventNodes` 遍历，并且钉住"树"才有的三种错误：

1. **入口段不存在**（`EV.Entry` 指向 `EventNodes` 里没有的 id）⇒ 玩家点进一个没有正文的房间；
2. **`Next` 指向不存在的段** ⇒ 点下去事件卡在原地（或干脆崩）；
3. **孤儿段** —— `EventNodes` 里有、却没有任何 `Entry`/`Next` 指到它 ⇒ 一段谁也看不见的剧情。

这三条都"没有症状"：镜像装得下、内核读得出、页面上一切正常。所以必须在内容门里穷尽。
"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'

OLD_START = '''def check_event_vocabulary(doc):'''
OLD_END = '''# =============================================================================
# 2b.  the fourth layer'''

NEW = '''def check_event_vocabulary(doc):
    """§278：每个事件是一棵**段树**，逐段检查选项与效果。

    判据（每一条对应一种没有症状的错误）：
    * 词表外的效果 ⇒ `fail`（点下去一个死按钮）；
    * `Effects*Asc` 与基础**一模一样** ⇒ "A15 变糟"什么都没变；
    * 一个选项里**两个改牌效果** ⇒ 待答的选牌只有一个位置，一定丢一个；
    * `EV.Entry` / `Next` 指向不存在的段、或者存在**孤儿段** ⇒ 剧情走不到/看不见。
    """
    print("[6c] event vocabulary (port-plan.md §278)")
    rooms = doc.get("UnknownRooms") or []
    nodes = doc.get("EventNodes") or []
    node_ids = [node.get("Id") for node in nodes]
    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    relics = {r["Id"] for r in doc.get("Relics") or []}
    counts = {"bare": 0, "curse": 0, "relic": 0, "percent": 0, "effects": 0, "asc": 0,
              "options": 0, "steps": 0}
    reached = set()
    for room in rooms:
        entry = room.get("Entry")
        if not entry:
            fail("UnknownRooms.%s" % room.get("Id"), "no Entry (this event has no first step)")
        elif entry not in node_ids:
            fail("UnknownRooms.%s.Entry" % room.get("Id"),
                 "names %r, which is not in EventNodes" % (entry,))
        else:
            reached.add(entry)

    for node in nodes:
        counts["steps"] += 1
        node_id = node.get("Id")
        label_root = "EventNodes.%s" % node_id
        if not node.get("TextKey"):
            fail(label_root, "empty TextKey (a step with no body text)")
        options = node.get("Options") or []
        if not isinstance(options, list):
            fail(label_root, "Options is not a list: %r" % (options,))
            continue
        counts["options"] += len(options)
        if len(options) < 2:
            fail(label_root, "%d option(s) -- an event step needs at least two" % len(options))
        if len(options) > 4:
            fail(label_root, "%d options (the kernel's MAX_EVENT_OPTIONS is 4)" % len(options))
        for index, option in enumerate(options):
            label = "%s.Options%d" % (label_root, index)
            if not option.get("Label"):
                fail(label, "empty Label (an unlabeled button)")
            nxt = option.get("Next") or ""
            if nxt:
                if nxt not in node_ids:
                    fail(label + ".Next", "names %r, which is not in EventNodes" % (nxt,))
                else:
                    reached.add(nxt)
            for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):
                effects = option.get(key)
                if effects is None:
                    effects = []
                if not isinstance(effects, list):
                    fail(label + "." + key, "not a list: %r" % (effects,))
                    continue
                if len(effects) > 4:
                    fail(label + "." + key, "more than 4 effects (the kernel's MAX_EVENT_EFFECTS)")
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
                        if effect in EVENT_DECK_EDITS:
                            edits += 1
                        continue
                    kind, _, payload = effect.partition(":")
                    if kind == "curse" and payload:
                        counts["curse"] += 1
                        if payload not in cards:
                            fail(where, "curse:%s 不是内容里的卡" % payload)
                        elif cards[payload] != "Curse":
                            fail(where, "curse:%s 的 Rarity 是 %s，不是 Curse"
                                 % (payload, cards[payload]))
                        continue
                    if kind == "relic" and payload:
                        counts["relic"] += 1
                        if payload not in relics:
                            fail(where, "relic:%s 不在 Relics 表里" % payload)
                        elif payload not in IMPLEMENTED_RELICS:
                            fail(where, "relic:%s 的效果内核没实现（%s）"
                                 % (payload, " / ".join(IMPLEMENTED_RELICS)))
                        continue
                    if kind in ("damage_pct", "max_hp_pct"):
                        counts["percent"] += 1
                        # 百分比必须在 1..=100：`0` 是一条什么也不做的效果（页面上还写着
                        # "按上限 0% 受伤"），而 `150` 会把最大 HP 扣成负数。
                        try:
                            percent = int(payload)
                        except (TypeError, ValueError):
                            fail(where, "百分比不是整数: %r" % (payload,))
                            continue
                        if not 1 <= percent <= 100:
                            fail(where, "百分比 %d 不在 1..=100" % percent)
                        if entry.get("Amount") not in (0, None):
                            fail(where, "百分比效果的 Amount 必须是 0（数字在词里）")
                        continue
                    fail(where, "词表外的效果 %r" % (effect,))
                if edits > 1:
                    fail(label + kind_label,
                         "%d 个改牌效果（待答选牌只有一个位置）" % edits)
            # §188：A15 的变体必须**真的不一样**。
            base = option.get("Effects") or []
            asc = option.get("EffectsAsc") or []
            if asc and asc == base:
                fail(label + "Asc", "the A15 list equals the base -- this ascension does nothing")

    # ★ 孤儿段：内容里有、却谁也走不到它。
    orphans = [node_id for node_id in node_ids if node_id not in reached]
    if orphans:
        fail("EventNodes", "unreachable step(s): %s" % ", ".join(str(o) for o in orphans))
    ok("event steps",
       "%d room(s) -> %d step(s) (%.2f steps/room), %d option(s), %d effect(s) "
       "(%d in A15 lists), %d bare / %d curse: / %d relic: / %d percent"
       % (len(rooms), counts["steps"], counts["steps"] / max(len(rooms), 1),
          counts["options"], counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"], counts["percent"]))
    # The three per-act pools must name rooms that exist, or the `?` room picks nothing.
    known = {room.get("Id") for room in rooms}
    tables = doc.get("EventTables") or {}
    for name in ("Events", "Events2", "Events3"):
        rows = tables.get(name)
        if not rows:
            fail("EventTables." + name, "missing or empty")
            continue
        for row in rows:
            if row.get("Id") not in known:
                fail("EventTables." + name, "%r is not in UnknownRooms" % (row.get("Id"),))
    ok("event pools", "act1=%d act2=%d act3=%d"
       % (len(tables.get("Events") or []), len(tables.get("Events2") or []),
          len(tables.get("Events3") or [])))


# =============================================================================
# 2b.  the fourth layer'''


def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END, start)
    old = s[start:end]
    assert 'UnknownRooms.%s.Effects%s' in old, 'region looks wrong'
    s = s[:start] + NEW + s[end + len(OLD_END):]
    # 词表常量：把两个百分比原子加进注释与查验
    s = s.replace('EVENT_BARE_EFFECTS = ',
                  '# §278: `damage_pct:<n>` / `max_hp_pct:<n>` 的 kind（数字在词里，不在 Amount 格）。\n'
                  'EVENT_PERCENT_EFFECTS = ("damage_pct", "max_hp_pct")\nEVENT_BARE_EFFECTS = ', 1)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('content gate: step-aware')


main()
