"""§222 A: close the two §218 deviations that were really just *our* mistakes.

1. `apparition` — wiki: base is **Ethereal** + "Gain 1 Intangible" + **Exhaust**; the upgrade removes
   Ethereal and keeps everything else. Content had no Ethereal at all and made the upgrade pay **2**
   Intangible -- the upgrade axis pointed the wrong way.
2. `buffer` — the §218 claim was "the wiki page is the v2.3 rework, we follow the old card". That was
   a **version excuse**: every other card in this content is pinned against the same wiki pages, so
   keeping one card on an older baseline means the content has two baselines. Align it:
   Power / Rare / 2 energy, 1 (2) Buffer.
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}

# ── apparition ─────────────────────────────────────────────────────────────────────────────────
base = cards['apparition']
plus = cards['apparition+']
assert 'ethereal' not in [tag['value'] for tag in base['Tags']], 'already fixed?'
base['Tags'].append({'value': 'ethereal'})
base['TurnEndHandDestinationZone'] = 'ExhaustPile'
base['DescriptionKey'] = 'Ethereal. Gain 1 Intangible. Exhaust.'
plus['Tags'] = [tag for tag in plus['Tags'] if tag['value'] != 'ethereal']
plus['TurnEndHandDestinationZone'] = 'Hand'
plus['DescriptionKey'] = 'Gain 1 Intangible. Exhaust.'

# 升级只去掉 Ethereal：两层都给 1 层无形。
for variant, stacks in (('apparition', 1), ('apparition+', 1)):
    card = cards[variant]
    node = card['Program']['Root']
    assert node['kind'] == 'node.applyStatus', node['kind']
    node['value']['Stacks'] = {'kind': 'const', 'value': {'Value': stacks}}
print('apparition: Ethereal on the base only, 1 Intangible on both sides')

# ── buffer：跟 wiki 走（Power / Rare / 2 费） ────────────────────────────────────────────────────
buffer = cards['buffer']
buffer['Rarity'] = 'Rare'
buffer['Tags'] = [{'value': 'power'}, {'value': 'buffer'}]
buffer['Costs'] = [{'ResourceId': {'value': 'standard.energy'}, 'Amount': 2}]
print('buffer: Power / Rare / 2 energy (the wiki baseline, like every other card here)')

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
