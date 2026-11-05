"""§218 content fixes: the four things the wiki pin caught as plain transcription errors.

Fixed here (cheap, no new mechanics):
  * `apparition` rarity Uncommon -> **Special** (it is a Special card from the Apparition event);
  * `blur` rarity Rare -> **Uncommon**;
  * `sentinel` rarity Common -> **Uncommon**;
  * `blur` never gave its Block: wiki says "Gain 5 (8) Block.", we only applied the Blur status.
    A missing number, not a design choice.

Declared instead (needs new mechanics or a content row; recorded in `native/card_wiki_inventory.py`):
  * `buffer` -- the wiki page is the v2.3 **rework** (Power / Rare / 2 energy); this content keeps the
    old Skill / Uncommon / 1 energy card.
  * `slimed` (we make it unplayable), `apparition` (upgrade gives 2 Intangible; no Ethereal/Exhaust),
    `sentinel` (we carry `ethereal`; no "when exhausted" payoff), `void` (no on-draw trigger),
    `burn+` (no 4-damage lifecycle), `bandage_up+` / `dark_shackles+` (no upgraded rows),
    `bandage_up` / `dark_shackles` (no `exhaust` tag -- exhaust-on-play has no carrier yet).
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}

RARITY = {'apparition': 'Special', 'blur': 'Uncommon', 'sentinel': 'Uncommon'}
for card_id, rarity in RARITY.items():
    before = cards[card_id]['Rarity']
    cards[card_id]['Rarity'] = rarity
    for variant in (card_id, card_id + '+'):
        if variant in cards:
            cards[variant]['Rarity'] = rarity
    print('rarity %-12s %s -> %s' % (card_id, before, rarity))


def block_node(amount):
    return {
        'kind': 'node.gainBlock',
        'value': {
            'TargetSelector': {'kind': 'sel.source',
                               'value': {'Cardinality': 'ZeroOrOne',
                                         'RequiredContextCapabilities': 'Source'}},
            'Amount': {'kind': 'const', 'value': {'Value': amount}},
            'PoolId': {'value': 'standard.block'},
            'ResultKey': None,
        },
    }


def with_block(card_id, amount):
    """把 `gainBlock` 插到程序最前面（wiki 的顺序就是 Block 在前、状态在后）。"""
    root = cards[card_id]['Program']['Root']
    node = block_node(amount)
    if root['kind'] == 'node.sequence':
        children = root['value']['Children']
        assert children and children[0].get('kind') == 'node.applyStatus', children[0].get('kind')
        children.insert(0, node)
    else:
        cards[card_id]['Program']['Root'] = {'kind': 'node.sequence',
                                             'value': {'Children': [node, root]}}
    print('block   %-12s +%d Block' % (card_id, amount))


with_block('blur', 5)
with_block('blur+', 8)

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
