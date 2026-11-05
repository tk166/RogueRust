"""§219: the two cards that spelled the exhaust zone wrong, plus the gate that would have caught it.

`PlayedCardDestinationZone` is an **enum name** the kernel resolves through `zone_from_wire_name`
(`play.rs:1931`), and that table has `ExhaustPile` -- not `Exhaust`. `bandage_up` and `dark_shackles`
said `"Exhaust"`, so **playing either one was an `IrError::UnknownKind`**. Nothing noticed because no
test ever played them (the C# oracle layer only authors the scenario package, and no rd-wasm test
touched these two).

This is the "exhaust on play" carrier the §218 inventory thought was missing: it existed, it was just
spelled wrong.
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}

fixed = []
for card_id in sorted(cards):
    card = cards[card_id]
    for key in ('PlayedCardDestinationZone', 'TurnEndHandDestinationZone'):
        if card.get(key) == 'Exhaust':
            card[key] = 'ExhaustPile'
            fixed.append('%s.%s' % (card_id, key))
assert fixed, 'nothing to fix: the spelling bug is gone?'
print('fixed:', ', '.join(fixed))

# `slimed`：wiki 说它 **1 费、可出、Exhaust**。内容把它做成"不可出"，因为当时没有"打出即消耗"的
# 载体 —— 现在有了（`PlayedCardDestinationZone = ExhaustPile`），就没有理由继续简化。
slimed = cards['slimed']
tags = [tag['value'] for tag in slimed['Tags']]
assert 'unplayable' in tags, tags
slimed['Tags'] = [tag for tag in slimed['Tags'] if tag['value'] != 'unplayable']
slimed['PlayedCardDestinationZone'] = 'ExhaustPile'
slimed['DescriptionKey'] = 'Exhaust.'
print('slimed: playable again, exhausts on play (wiki: "Exhaust.")')

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
