"""§220 part B: content + gates for `Drawn` / `Exhausted`.

* `void`: wiki "Whenever this card is drawn, lose 1 Energy." -> `LifecyclePrograms.Drawn`.
* `sentinel`: wiki "If this card is Exhausted, gain 2 (3) Energy." -> `LifecyclePrograms.Exhausted`
  (base 2, `sentinel+` 3 -- the lifecycle lives on the **definition**, so the upgraded row needs its
  own copy).
* `program_facts` learns the two resource nodes, so those facts are pinned instead of invisible.
* `check_card_lifecycle` pins the **key set** and the facts, both directions: a card that grows a
  lifecycle program nobody recorded turns the gate red, and a recorded program that disappears does too.
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}


def resource_node(kind, amount):
    return {
        'Id': {'Value': '(unnamed)'},
        'Root': {
            'kind': 'node.' + kind,
            'value': {
                'TargetSelector': {'kind': 'sel.source',
                                   'value': {'Cardinality': 'ZeroOrOne',
                                             'RequiredContextCapabilities': 'Source'}},
                'ResourceId': 'standard.energy',
                'Amount': {'kind': 'const', 'value': {'Value': amount}},
                'ResultKey': None,
            },
        },
        'MaxNodeDepth': 64,
        'MaxProgramSteps': 1024,
    }


for card_id, event, kind, amount in [
    ('void', 'Drawn', 'loseResource', 1),
    ('void+', 'Drawn', 'loseResource', 1),
    ('sentinel', 'Exhausted', 'gainResource', 2),
    ('sentinel+', 'Exhausted', 'gainResource', 3),
]:
    card = cards.get(card_id)
    if card is None:
        continue
    programs = card.get('LifecyclePrograms') or {}
    assert event not in programs, '%s already has %s' % (card_id, event)
    programs[event] = resource_node(kind, amount)
    card['LifecyclePrograms'] = programs
    print('%-12s %s -> %s %d energy' % (card_id, event, kind, amount))

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
