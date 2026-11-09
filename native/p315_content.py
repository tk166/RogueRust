"""§315（二）：`Sentry and Spheric Guardian` —— Act 2 的最后一条（13 / 13 的真正补齐）。

wiki（`The_City` 的 Hard 池）：1 Sentry + 1 Spheric Guardian，权重 2。

两条注意：
1. **Sentry 的 `MaxHealthAsc` 与精英遭遇里那条一模一样**（`{A8, 39}`）—— 这正是 §315 建模的
   意义：钉的是怪物自己的表，不是池子的档位。
2. Spheric Guardian 的 40 Block 走遭遇的 `StartingBlock`（§208），不是状态。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    assert not any(e['Id']['Value'] == 'enc_sentry_and_spheric' for e in doc['Encounters'])

    sentries = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_three_sentries')
    sentry = json.loads(json.dumps(sentries['Enemies'][0]))
    sentry['Position'] = 0
    assert sentry['MaxHealthAsc'] == [{'AscensionMin': 8, 'MaxHealth': 39}]

    spheric = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_spheric_guardian')
    guardian = json.loads(json.dumps(spheric['Enemies'][0]))
    guardian['Position'] = 1
    guardian['StartingBlock'] = 40

    encounter = {
        'Id': {'Value': 'enc_sentry_and_spheric'},
        'Enemies': [sentry, guardian],
        'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    doc['Encounters'].append(encounter)
    # wiki 的 Hard 池权重 2 ⇒ ×5 = 10
    doc['EncounterTables']['Weak2'].append({'Id': 'enc_sentry_and_spheric', 'Weight': 10})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('encounters %d weak2 %d' % (len(doc['Encounters']),
                                     len(doc['EncounterTables']['Weak2'])))


main()
