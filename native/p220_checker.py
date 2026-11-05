"""§220 part C: pin the lifecycle programs (the gate that makes the carriers real)."""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# ① program_facts：资源节点（否则 `Drawn`/`Exhausted` 的事实列表是空的，pin 没有区分力）
one('''        elif kind == "node.extraTurn":''',
    '''        elif kind in ("node.gainResource", "node.loseResource"):
            # §220: the two halves of "whenever this card is drawn, lose 1 Energy" /
            # "if this card is Exhausted, gain 2 Energy". Recorded as a fact so the gate can see
            # them -- a lifecycle program the inventory does not mention would otherwise be
            # invisible (this function is the only vocabulary the checker has).
            words = "gain" if kind == "node.gainResource" else "lose"
            facts.append((words, body["ResourceId"], amount(body["Amount"]),
                          tgt(body["TargetSelector"])))
        elif kind == "node.extraTurn":''',
    'facts: resources')

# ③ 新检查：生命周期节目的键集合与事实，两个方向都查
one('''def check_card_wiki(doc):''',
    '''CARD_LIFECYCLE_EVENTS = ("TurnEndInHand", "Drawn", "Exhausted")


def check_card_lifecycle(doc):
    """§220：`CARD.LifecyclePrograms` 的**键集合**与**事实**，两个方向都查。

    为什么要有这一层：这些节目不在卡的 `Program` 里，所以 `INV_CARDS` 的 `Facts` 一行**看不见**
    它们 —— 内容把一条节目删掉/写错时，只有这张表会红。`void` 与 `sentinel` 是这一节新加的两条
    （`Drawn` / `Exhausted` 两个事件本身也是这一节新加的内核能力）。
    """
    cards = {card["Id"]: card for card in doc["Cards"]}
    seen = 0
    for card_id in sorted(cards):
        programs = cards[card_id].get("LifecyclePrograms") or {}
        expected = (INV_CARDS.get(card_id) or {}).get("Lifecycle") or {}
        for key in programs:
            if key not in CARD_LIFECYCLE_EVENTS:
                fail("card." + card_id, "生命周期事件 %r 内核不认识（认识的是 %s）"
                     % (key, list(CARD_LIFECYCLE_EVENTS)))
                continue
            if key not in expected:
                fail("card." + card_id, "有一条 `%s` 生命周期节目，`INV_CARDS` 没有记录" % key)
                continue
            seen += 1
            facts = program_facts(programs[key]["Root"])
            if facts != expected[key]:
                fail("card." + card_id, "`%s` 节目事实 %s，inv says %s"
                     % (key, facts, expected[key]))
        for key in expected:
            if key not in programs:
                fail("card." + card_id, "`INV_CARDS` 记了 `%s` 节目，内容里没有" % key)
    return seen


def check_card_wiki(doc):''',
    'lifecycle check')

one('''    ok("card zones", "%d zone cells x 7 known names" % check_card_zones(doc))''',
    '''    ok("card zones", "%d zone cells x 7 known names" % check_card_zones(doc))
    ok("card lifecycle", "%d program(s) x (event key, facts)" % check_card_lifecycle(doc))''',
    'wire lifecycle')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('checker patched')
