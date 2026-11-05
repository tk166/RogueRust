"""§219 checker: zone names are a vocabulary, and wiki's `Exhaust` is a zone, not a tag.

Two additions:

1. `check_card_zones` -- `PlayedCardDestinationZone` / `TurnEndHandDestinationZone` are **enum names**
   the kernel resolves through `zone_from_wire_name`; a typo there is an `IrError::UnknownKind` at
   play time, i.e. a card that looks fine and cannot be played. `bandage_up` and `dark_shackles` sat
   like that for weeks (`"Exhaust"` instead of `"ExhaustPile"`), and no test played them.
2. the card-wiki layer now compares the wiki's `Exhaust` keyword against the **zone**
   (`PlayedCardDestinationZone == "ExhaustPile"`), not against a tag -- because that is where the
   behaviour lives (`play.rs` copies the card to that zone after resolving it). §218 compared it to a
   tag, so two cards were wrongly declared "missing the Exhaust carrier".
"""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# ── ① 区名白名单 ────────────────────────────────────────────────────────────────────────────────
one('''def check_card_wiki(doc):''',
    '''CARD_ZONE_NAMES = {"DrawPile", "Hand", "DiscardPile", "ExhaustPile", "BanishedPile",
                   "QueuePile", "SetAsidePile"}


def check_card_zones(doc):
    """§219：两张卡牌落区字段的值必须是内核认识的**枚举名**。

    判据来自 `play.rs:1931` 的 `zone_from_wire_name`：它只认上表那七个串，别的一律
    `IrError::UnknownKind` —— 也就是说"写错一个词"= 这张牌一打就抛。`bandage_up` /
    `dark_shackles` 曾经写着 `"Exhaust"`（正确是 `"ExhaustPile"`），因为**没有任何测试打过它们**，
    这个错从 §157 一直活到 §218 的卡牌 wiki 对照才发现。
    """
    seen = 0
    for card in doc["Cards"]:
        for key in ("PlayedCardDestinationZone", "TurnEndHandDestinationZone"):
            name = card.get(key)
            if name is None:
                continue
            seen += 1
            if name not in CARD_ZONE_NAMES:
                fail("card." + card["Id"], "%s = %r 不是区名（认识的是 %s）"
                     % (key, name, sorted(CARD_ZONE_NAMES)))
    return seen


def check_card_wiki(doc):''',
    'zone check')

# ── ② wiki 的 Exhaust 关键字 ↔ 落区（不再是 tag） ───────────────────────────────────────────────
one('''        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag
        expected_keywords = deviation.get('content_keywords')
        if expected_keywords is None:
            expected_keywords = wiki['keywords']
        expected_tags = {KEYWORD_TAGS[name] for name in expected_keywords}
        missing = expected_tags - tags
        if missing:
            fail("card." + card_id, "缺少关键字 tag %s（wiki %s）"
                 % (sorted(missing), wiki['keywords']))
        # 反向：内容有 ethereal/exhaust 而 wiki 没有 —— 也要红（`sentinel` 就是这条）
        extra = (tags & {'ethereal', 'exhaust', 'innate', 'retain'}) - expected_tags
        if extra and 'content_keywords' not in deviation:
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))''',
    '''        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag / 落区。
        #    ⚠️ §219：`Exhaust` 不是 tag，而是 **`PlayedCardDestinationZone = ExhaustPile`**
        #    （`play.rs:1931` 在那里把牌送进消耗堆）。§218 把它当 tag 比，于是 `bandage_up` /
        #    `dark_shackles` 被误判成"缺载体"——它们其实有，只是落区写错了一个词（见 `check_card_zones`）。
        expected_keywords = deviation.get('content_keywords')
        if expected_keywords is None:
            expected_keywords = wiki['keywords']
        zone_keywords = {'Exhaust'}
        expected_tags = {KEYWORD_TAGS[name] for name in expected_keywords
                         if name not in zone_keywords}
        missing = expected_tags - tags
        if missing:
            fail("card." + card_id, "缺少关键字 tag %s（wiki %s）"
                 % (sorted(missing), wiki['keywords']))
        exhausts = card.get("PlayedCardDestinationZone") == "ExhaustPile"
        if ("Exhaust" in expected_keywords) != exhausts:
            fail("card." + card_id, "wiki %s Exhaust，内容的落区是 %r"
                 % ("有" if "Exhaust" in expected_keywords else "没有",
                    card.get("PlayedCardDestinationZone")))
        # 反向：内容有 ethereal/exhaust 而 wiki 没有 —— 也要红（`sentinel` 就是这条）
        extra = (tags & {'ethereal', 'innate', 'retain'}) - expected_tags
        if extra and 'content_keywords' not in deviation:
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))''',
    'exhaust is a zone')

# ── ③ 接进主流程 ────────────────────────────────────────────────────────────────────────────────
one('''    ok("card wiki", "%d cards x (type, rarity, cost, keywords, facts)" % check_card_wiki(doc))''',
    '''    ok("card zones", "%d zone cells x 7 known names" % check_card_zones(doc))
    ok("card wiki", "%d cards x (type, rarity, cost, keywords, facts)" % check_card_wiki(doc))''',
    'wire zones')

# ── ④ INV_CARDS 的 slimed 行：现在可出、落区 ExhaustPile ────────────────────────────────────────
one('''    "slimed": {"Cost": 1, "Tags": ["status", "unplayable", "junk"],
               "Facts": []},''',
    '''    # §219：wiki 是"1 费、可出、Exhaust"。落区现在写得出来了（`PlayedCardDestinationZone`），
    # 所以不再需要 `unplayable` 这个简化。
    "slimed": {"Cost": 1, "Tags": ["status", "junk"], "Facts": [],
               "PlayedCardDestinationZone": "ExhaustPile"},''',
    'INV_CARDS slimed')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('checker patched')
