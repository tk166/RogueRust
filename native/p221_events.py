"""§221 events: two two-option rooms + the two curses they hand out.

The room model has exactly **two** options (`Effects0` / `Effects1`, plus the A15 variants), so only
two-option wiki events can be expressed without extending the ABI. Both of these are real Act-1/Act-2
events whose effects stay inside the closed `EventEffect` vocabulary:

* `the_ssssserpent`  -- "Agree": +175 gold and a **Doubt**; "Disagree": nothing.
* `the_mausoleum`    -- "Open Coffin": a relic and a **Writhe**; "Leave": nothing.

`Doubt` is also the third card with a lifecycle program: wiki says "At the end of your turn, gain 1
Weak", i.e. `LifecyclePrograms[TurnEndInHand]` -- the carrier from §220, no new mechanism.
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))
cards = {card['Id']: card for card in doc['Cards']}

SOURCE = {'kind': 'sel.source', 'value': {'Cardinality': 'ZeroOrOne',
                                          'RequiredContextCapabilities': 'Source'}}


def status(name, stacks, target=SOURCE):
    return {'kind': 'node.applyStatus', 'value': {'TargetSelector': target,
                                                  'StatusDefinitionId': {'value': name},
                                                  'Stacks': {'kind': 'const', 'value': {'Value': stacks}},
                                                  'DurationTurns': 0, 'Charges': 0,
                                                  'ResultKey': None}}


def program(children):
    root = children[0] if len(children) == 1 else {'kind': 'node.sequence',
                                                   'value': {'Children': children}}
    return {'Id': {'Value': '(unnamed)'}, 'Root': root, 'MaxNodeDepth': 64,
            'MaxProgramSteps': 1024}


NEW_CURSES = [
    # (id, name, description, tags, lifecycle)
    ('doubt', 'Doubt', 'At the end of your turn, gain 1 Weak.',
     ['curse', 'unplayable'],
     {'TurnEndInHand': program([status('standard.weak', 1)])}),
    ('writhe', 'Writhe', 'Innate. Unplayable.', ['curse', 'unplayable', 'innate'], {}),
]
for card_id, name, description, tags, lifecycle in NEW_CURSES:
    assert card_id not in cards, card_id
    doc['Cards'].append({
        'Id': card_id,
        'PackageId': 'sts',
        'NameKey': name,
        'DescriptionKey': description,
        'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': 1}],
        'Tags': [{'value': tag} for tag in tags],
        'Rarity': 'Curse',
        'Program': program([{'kind': 'node.sequence', 'value': {'Children': []}}]),
        'PlayedCardDestinationZone': 'DiscardPile',
        'TurnEndHandDestinationZone': 'Hand',
        'RetainInHandOnTurnEnd': False,
        'LifecyclePrograms': lifecycle,
    })
    print('curse %s added' % card_id)

NEW_ROOMS = [
    {
        'Id': 'the_ssssserpent',
        'NameKey': 'The Ssssserpent',
        'DescriptionKey': 'A giant serpent offers you a deal.',
        'Label0': 'Agree',
        'Label1': 'Disagree',
        'Effects0': [{'Effect': 'gold', 'Amount': 175}, {'Effect': 'curse:doubt', 'Amount': 1}],
        'Effects1': [{'Effect': 'nothing', 'Amount': 0}],
        'Effects0Asc': [{'Effect': 'gold', 'Amount': 175}, {'Effect': 'curse:doubt', 'Amount': 2}],
    },
    {
        'Id': 'the_mausoleum',
        'NameKey': 'The Mausoleum',
        'DescriptionKey': 'A coffin waits in the dark.',
        'Label0': 'Open Coffin',
        'Label1': 'Leave',
        'Effects0': [{'Effect': 'relic:strawberry', 'Amount': 1},
                     {'Effect': 'curse:writhe', 'Amount': 1}],
        'Effects1': [{'Effect': 'nothing', 'Amount': 0}],
    },
]
rooms = {room['Id']: room for room in doc['UnknownRooms']}
for room in NEW_ROOMS:
    assert room['Id'] not in rooms, room['Id']
    doc['UnknownRooms'].append(room)
    print('room %s added' % room['Id'])

# 两个房间进**第二幕**的池子（wiki：Mausoleum 在 Act 2+；Ssssserpent 在 Act 1，
# 但第一幕的池子已经够满，先把它放在 Act 2 的“额外”位 —— 这是**内容选择**，写在这里而不是猜）。
for table, room_id in (('Events2', 'the_mausoleum'), ('Events3', 'the_ssssserpent')):
    entries = doc['EventTables'][table]
    assert all(entry['Id'] != room_id for entry in entries), room_id
    entries.append({'Id': room_id})
    print('%s += %s' % (table, room_id))

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
