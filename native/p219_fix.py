"""§219 fix-up: swap the keyword block for the zone-aware one (the earlier patch missed it)."""
import io

P = 'native/sts_content_check.py'
text = io.open(P, encoding='utf-8').read()

old = '''        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag
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
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))'''

new = '''        # ④ 关键字：`{{KW|X}}`（不带竖线的才算）↔ tag / 落区。
        #    ⚠️ §219：`Exhaust` 不是 tag，而是 **`PlayedCardDestinationZone = ExhaustPile`**
        #    （`play.rs:1931` 在那里把牌送进消耗堆）。§218 把它当 tag 比，于是 `bandage_up` /
        #    `dark_shackles` 被误判成"缺载体" —— 它们其实有，只是落区写错了一个词
        #    （那个拼写 bug 由 `check_card_zones` 与本节一起抓）。
        expected_keywords = deviation.get('content_keywords')
        if expected_keywords is None:
            expected_keywords = wiki['keywords']
        expected_tags = {KEYWORD_TAGS[name] for name in expected_keywords
                         if name in KEYWORD_TAGS}
        missing = expected_tags - tags
        if missing:
            fail("card." + card_id, "缺少关键字 tag %s（wiki %s）"
                 % (sorted(missing), wiki['keywords']))
        exhaust_expected = "Exhaust" in expected_keywords
        exhaust_actual = card.get("PlayedCardDestinationZone") == "ExhaustPile"
        if exhaust_expected != exhaust_actual:
            fail("card." + card_id, "wiki %s Exhaust，内容的落区是 %r"
                 % ("有" if exhaust_expected else "没有",
                    card.get("PlayedCardDestinationZone")))
        # 反向：内容有 ethereal/innate/retain 而 wiki 没有 —— 也要红（`sentinel` 就是这条）
        extra = (tags & {'ethereal', 'innate', 'retain'}) - expected_tags
        if extra and 'content_keywords' not in deviation:
            fail("card." + card_id, "多出关键字 tag %s（wiki 没有）" % sorted(extra))'''

assert text.count(old) == 1, text.count(old)
io.open(P, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
print('keyword block is zone-aware now')
