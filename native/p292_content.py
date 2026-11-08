"""§292 Wave 1 内容：11 件遗物 + `standard.cursed_key`（每回合 +1 能量）。

⚠️ 稀有度**照 wiki**（`calling_bell`/`cursed_key`/`sacred_bark` = Boss、`cauldron`/`dollys_mirror` = Shop、
`nloths_gift`/`nloths_hungry_face`/`face_of_cleric`/`cultist_headpiece`/`spirit_poop` = Event、
`matryoshka` = Uncommon）。`Shop` 档正是 §292 新加的桶 —— 它今天**只能从商人货架**来。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'

# id -> (DisplayName, Rarity)
RELICS = {
    'cultist_headpiece': ('Cultist Headpiece', 'Event'),
    'spirit_poop': ('Spirit Poop', 'Event'),
    'face_of_cleric': ('Face of Cleric', 'Event'),
    'nloths_hungry_face': ("N'loth's Hungry Face", 'Event'),
    'nloths_gift': ("N'loth's Gift", 'Event'),
    'matryoshka': ('Matryoshka', 'Uncommon'),
    'cursed_key': ('Cursed Key', 'Boss'),
    'calling_bell': ('Calling Bell', 'Boss'),
    'sacred_bark': ('Sacred Bark', 'Boss'),
    'cauldron': ('Cauldron', 'Shop'),
    'dollys_mirror': ("Dolly's Mirror", 'Shop'),
}

# `standard.cursed_key`：每回合 +1 能量。载体是 `PassiveModifiers` 的 `TurnStartEnergy`
# （与 `standard.busted_crown` / `standard.slavers_collar` / `standard.sozu` 同一个形状）——
# 不学 `standard.lantern`：那个只给**第一回合**（它有计数器），而 `cursed_key` 是每回合。
CURSED_KEY_STATUS = {
    'Id': 'standard.cursed_key',
    'PackageId': 'sts',
    'NameKey': 'Cursed Key',
    'DescriptionKey': 'Gain 1 Energy at the start of your turn.',
    'Polarity': 'Buff',
    'UsesStacks': True,
    'UsesDuration': False,
    'UsesCharges': False,
    'StackingBehavior': 'MergeWithExistingInstance',
    'Tags': ['buff'],
    'PassiveModifiers': [{
        'Pipeline': 'TurnStartEnergy',
        'Operation': 'AddPerStack',
        'Magnitude': 1,
        'Priority': 100,
        'RestrictDamageKind': None,
        'AppliesToStatusId': None,
        'RestrictSourceCardTag': None,
    }],
    'Triggers': [],
}


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Relics']}
    for relic_id, (name, rarity) in RELICS.items():
        if relic_id in have:
            continue
        doc['Relics'].append({
            'Id': relic_id,
            'DisplayName': name,
            'RunPrograms': None,
            'CombatRules': None,
            'Rarity': rarity,
        })
    status_ids = {row['Id'] for row in doc['Statuses']}
    if 'standard.cursed_key' not in status_ids:
        doc['Statuses'].append(CURSED_KEY_STATUS)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: %d relics, statuses %d' % (len(doc['Relics']), len(doc['Statuses'])))

    # 内容门的第二意见清单（手抄，`IMPLEMENTED_RELICS`）
    gate = io.open(GATE, encoding='utf-8').read()
    anchor = '''                      "snecko_eye",'''
    assert gate.count(anchor) == 1
    gate = gate.replace(anchor, anchor + '''
                      # §292 Wave 1：11 件（flavor-only 两件、拾取欠账两件、宝箱三件、奖励/药水/复制各一件）。
                      "cultist_headpiece", "spirit_poop", "face_of_cleric", "matryoshka",
                      "nloths_hungry_face", "cursed_key", "calling_bell", "cauldron",
                      "dollys_mirror", "nloths_gift", "sacred_bark",''')
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(gate)
    print('gate list updated')


main()
