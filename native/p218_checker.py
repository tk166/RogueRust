"""§218: pin every card against its wiki page (type / rarity / cost / keywords / numbers)."""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


one('''INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}''',
    '''INV_UNWIRED = {"louse_green.bite", "louse_green.grow"}

# §218：每张卡的 wiki 页面。**字段**（type / rarity / cost / 关键字）在检查时从 dump 里读
# （`native/wiki_cards.py`），**数字**在 `native/card_wiki_inventory.py` 里人工冻结
# （wiki 的 Description 是散文，解析它等于在闸门里再实现一遍规则）。两边都指向同一份 dump，
# 所以任何一个数字都能离线复查。
CARD_WIKI = None            # 见 `load_card_wiki()`（延迟加载：导入 checker 的脚本不一定要它）
CARD_WIKI_DEVIATIONS = {}   # 基础 id -> 已知偏差的说明（矩阵的 Deviation 列会用它）

# 本内容有、wiki 没有的卡（样例包自带的）。**列出来**，不静默跳过。
NO_WIKI_PAGE = {
    'patient_guard': '本内容自有（样例包），wiki 没有这张牌',
    'swift_strike': '本内容自有（样例包），wiki 没有这张牌',
}

KEYWORD_TAGS = {'Unplayable': 'unplayable', 'Ethereal': 'ethereal',
                'Exhaust': 'exhaust', 'Innate': 'innate', 'Retain': 'retain'}


def load_card_wiki():
    """→ {基础 id: {'wiki': parse(...), 'base': [...], 'plus': [...] | None, 'deviation': {...}}}。"""
    global CARD_WIKI, CARD_WIKI_DEVIATIONS
    if CARD_WIKI is not None:
        return CARD_WIKI
    import card_wiki_inventory as W          # noqa: E402  (native/ 已在 sys.path 上)
    import wiki_cards
    out = {}
    for card_id in sorted(W.FACTS):
        deviation = W.DEVIATIONS.get(card_id, {})
        out[card_id] = {
            'wiki': wiki_cards.parse(card_id),
            'base': deviation.get('base_facts', W.FACTS[card_id][0]),
            'plus': deviation.get('plus_facts', W.FACTS[card_id][1]),
            'deviation': deviation,
        }
        if deviation.get('why'):
            CARD_WIKI_DEVIATIONS[card_id] = deviation['why']
    CARD_WIKI = out
    return out


def check_card_wiki(doc):
    """每张有 wiki 页面的卡：类型 / 稀有度 / 费用 / 关键字 / 数字，五项分开判。

    这一层补的是"内容门的清单也是人抄的"那个洞（§195.9：`blind` 的稀有度与 Exhaust 都写错过，
    而当时 20 道闸门全绿）。
    """
    inventory = load_card_wiki()
    cards = {card["Id"]: card for card in doc["Cards"]}
    checked = 0
    for card_id in sorted(inventory):
        entry = inventory[card_id]
        wiki = entry["wiki"]
        deviation = entry["deviation"]
        card = cards.get(card_id)
        if card is None:
            fail("card." + card_id, "wiki 页在、内容里没有这张卡")
            continue
        tags = {tag["value"] for tag in (card.get("Tags") or [])}

        # ① 类型：wiki 的 Attack/Skill/Power/Status/Curse 必须出现在内容的 tag 里
        #    （`buffer` 例外：wiki 页面已是 v2.3 的重做版（Power/Rare/2 费），本内容按旧版
        #     Skill/Uncommon/1 费 —— 那一条在偏差表里写明了）。
        if not deviation.get('content_type'):
            if wiki['type'] not in tags:
                fail("card." + card_id, "type %r 不在 tags %s 里（wiki `%s`）"
                     % (wiki['type'], sorted(tags), wiki['name']))

        # ② 稀有度：curse 的页面不写 Rarity，内容写 Curse
        expected_rarity = deviation.get('content_rarity')
        if expected_rarity is None:
            expected_rarity = wiki['rarity'] or ('Curse' if wiki['type'] == 'curse' else None)
        if expected_rarity is not None:
            actual = card.get('Rarity')
            if actual != expected_rarity:
                fail("card." + card_id, "rarity %r，wiki 说 %r" % (actual, expected_rarity))

        # ③ 费用：wiki 用 -1 表示 X 费、-2 表示不可出，内容用 tag 表达同一件事
        expected_cost = deviation.get('content_cost')
        if expected_cost is None:
            if wiki['cost'] == -1:
                expected_cost = 'x_cost'
            elif wiki['cost'] == -2:
                expected_cost = 'unplayable'
            else:
                expected_cost = wiki['cost']
        if expected_cost == 'x_cost':
            if 'x_cost' not in tags:
                fail("card." + card_id, "wiki 是 X 费，内容没有 `x_cost` tag")
        elif expected_cost == 'unplayable':
            if 'unplayable' not in tags:
                fail("card." + card_id, "wiki 是不可出，内容没有 `unplayable` tag")
        else:
            costs = [(cost["ResourceId"]["value"], cost["Amount"])
                     for cost in (card.get("Costs") or [])]
            if not any(resource.endswith("energy") and amount == expected_cost
                       for resource, amount in costs):
                fail("card." + card_id, "费用 %s，wiki 说 %d" % (costs, expected_cost))

        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag
        expected_keywords = deviation.get('content_keywords')
        if expected_keywords is None:
            expected_keywords = wiki['keywords']
        expected_tags = {KEYWORD_TAGS[name] for name in expected_keywords}
        missing = expected_tags - tags
        if missing:
            fail("card." + card_id, "缺少关键字 tag %s（wiki %s）"
                 % (sorted(missing), wiki['keywords']))
        # 反向：内容有 ethereal/exhaust 而 wiki 没有 —— 也要红（`sentinel` 就是这条）
        extra = ({tags & {'ethereal', 'exhaust', 'innate', 'retain'}}) - expected_tags
        if extra and 'content_keywords' not in deviation:
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))

        # ⑤ 数字：基础行与升级行分开比（`INV_CARDS` 的 Facts 就是从程序里抽出来的同一套词表）
        checked += 1
        base_facts = INV_CARDS[card_id]["Facts"]
        if sorted(map(repr, base_facts)) != sorted(map(repr, entry["base"])):
            fail("card." + card_id, "facts %s，wiki 说 %s" % (list(base_facts), entry["base"]))
        plus_id = card_id + "+"
        if entry["plus"] is None:
            if plus_id in INV_CARDS:
                fail("card." + plus_id, "内容有升级行，但 wiki 的升级只改关键字/目标（没有数字）")
        else:
            if plus_id not in INV_CARDS:
                fail("card." + plus_id, "wiki 有升级数字 %s，内容没有这一行" % (entry["plus"],))
            else:
                plus_facts = INV_CARDS[plus_id]["Facts"]
                if sorted(map(repr, plus_facts)) != sorted(map(repr, entry["plus"])):
                    fail("card." + plus_id, "facts %s，wiki 说 %s"
                         % (list(plus_facts), entry["plus"]))

    # 没有 wiki 页的两张牌必须**还是**那两张（内容加了新牌就该有人去找页面）
    for card_id, reason in sorted(NO_WIKI_PAGE.items()):
        if card_id not in cards:
            fail("card." + card_id, "`NO_WIKI_PAGE` 声明的 %s 在内容里不存在（声明烂了）：%s"
                 % (card_id, reason))
        elif card_id in inventory:
            fail("card." + card_id, "已经有 wiki 页了，`NO_WIKI_PAGE` 里那一条该删掉")
        elif card_id + "+" in cards:
            pass      # 升级行沿用同一张页面，没有独立页面是正常的
    return checked''',
    'card wiki layer')

one('''    check_intent_history(doc)
    check_time_variables(doc)''',
    '''    check_intent_history(doc)
    check_time_variables(doc)
    ok("card wiki", "%d cards x (type, rarity, cost, keywords, facts)" % check_card_wiki(doc))''',
    'wire into the run')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('checker: card wiki layer added')
