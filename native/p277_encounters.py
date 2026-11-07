"""§277 第三条（第二版）：`Exordium Thugs` / `Exordium Wildlife` —— 组合槽里放**完整记录**。

## 第一版的错（重要）

我给候选只写了 `Id / Weight / MaxHealth / MaxHealthAsc`，以为"它只是个引用"。**不行**：
战斗构建方是从**记录本身**读 `Actions` / `IntentRules` / `StartingStatuses` 的
（`spec.actions()`，`rd-wasm/lib.rs:1936`），所以只写 Id 的候选会造出一只**没有招式**的怪 ——
而且不会崩：那只怪每回合"什么都不做"。

⇒ 候选必须是**完整的敌人记录**（与 `Enemies` 的元素同形），只多一个 `Weight`。
所以这里用 §275 学到的做法：从既有遭遇（或 roster）**克隆**一条同 id 的记录，改 HP、加 `Weight`。

## wiki（wiki.gg `Exordium` + slayspiredb 一致）

* `Exordium Thugs`（权重 1.5）：第一个 = Louse（任色）或 Medium Slime（任型）；
  第二个 = Slaver（任色）或 Cultist 或 Looter。
* `Exordium Wildlife`（权重 1.5）：第一个 = Fungi Beast 或 Jaw Worm；第二个 = Louse 或 Medium Slime。

每个"或"是一个 `Candidates` 槽，候选权重都是 1（原作每只独立掷，等价均匀）。
"""
import copy
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

# 每个候选：怪物 id、本遭遇里的 HP、A7 HP。HP 沿用同族固定遭遇那一份（下界 / A7 上界）。
THUGS_SLOT0 = [('louse_red', 10, 11), ('louse_green', 11, 12),
               ('acid_slime_m', 28, 29), ('spike_slime_m', 28, 29)]
THUGS_SLOT1 = [('slaver_red', 46, 48), ('blue_slaver', 46, 48),
               ('cultist', 48, 50), ('looter', 44, 46)]
WILDLIFE_SLOT0 = [('fungi_beast', 22, 24), ('jaw_worm', 40, 42)]
WILDLIFE_SLOT1 = list(THUGS_SLOT0)


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']

    # 模板：既有遭遇行优先，其次 roster 行（roster 缺 `Position`/`DisplayName`，补齐）。
    template = {}
    for encounter in doc['Encounters']:
        for enemy in encounter['Enemies']:
            if 'Id' in enemy:
                template.setdefault(enemy['Id'], enemy)
    for monster in doc['Monsters']:
        mid = ids(monster)
        if mid in template:
            continue
        template[mid] = {
            'Id': mid,
            'MaxHealth': monster.get('MaxHealth', 10),
            'Actions': monster.get('Actions') or [],
            'StartingStatuses': monster.get('StartingStatuses') or [],
            'Position': None,
            'IntentRules': monster.get('IntentRules') or [],
            'DisplayName': monster.get('NameKey', mid),
            'Rolls': monster.get('Rolls') or [],
            'Counters': monster.get('Counters') or [],
            'Spawn': monster.get('Spawn', True),
            'MaxHealthAsc': monster.get('MaxHealthAsc') or [],
        }

    def candidate(mid, hp, asc):
        row = copy.deepcopy(template[mid])
        row['MaxHealth'] = hp
        row['MaxHealthAsc'] = [{'AscensionMin': 7, 'MaxHealth': asc}]
        row.pop('Position', None)
        row['Weight'] = 1
        return row

    def encounter(eid, slots):
        return {
            'Id': {'Value': eid},
            'Enemies': [
                {'Position': position,
                 'Candidates': [candidate(*spec) for spec in specs]}
                for position, specs in enumerate(slots)
            ],
            'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        }

    have = {ids(row) for row in doc['Encounters']}
    # 幂等：先删再写
    doc['Encounters'] = [e for e in doc['Encounters']
                         if ids(e) not in ('enc_exordium_thugs', 'enc_exordium_wildlife')]
    doc['EncounterTables']['Weak'] = [
        r for r in doc['EncounterTables']['Weak']
        if r['Id'] not in ('enc_exordium_thugs', 'enc_exordium_wildlife')]

    doc['Encounters'].append(encounter('enc_exordium_thugs', [THUGS_SLOT0, THUGS_SLOT1]))
    doc['Encounters'].append(encounter('enc_exordium_wildlife', [WILDLIFE_SLOT0, WILDLIFE_SLOT1]))
    for eid in ('enc_exordium_thugs', 'enc_exordium_wildlife'):
        doc['EncounterTables']['Weak'].append({'Id': eid, 'Weight': 10})

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('encounters %d, Weak %d (composed slots carry full records)'
          % (len(doc['Encounters']), len(doc['EncounterTables']['Weak'])))


main()
