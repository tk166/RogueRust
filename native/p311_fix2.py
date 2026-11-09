"""§311（四）：新遭遇的敌人行要从**已有的敌人记录**抄，而不是从怪物表现拼。

判据当场抓到了这件事：`cultist` / `shelled_parasite` / `fungi_beast` 在 Act 2 的池子里被要求
带一条 `MaxHealthAsc`（A7 的血量），而我们的 `Monsters` 表里**没有**这个字段 —— 它挂在
**遭遇的敌人记录**上（`enc_cultist` 的敌人行里就有 `AscensionMin: 7, MaxHealth: 50`）。

所以：模板取"任意一条同 id 的既有敌人记录"，只覆盖 `Position` / `MaxHealth` / `StartingBlock`。
这也顺带保证新遭遇的 `Actions` / `IntentRules` / `Rolls` 与既有那条**逐字段一致**。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

REBUILD = ['enc_chosen_and_byrd', 'enc_cultist_and_chosen', 'enc_three_cultists',
           'enc_parasite_and_fungi']


def enc_id(encounter):
    return encounter['Id']['Value'] if isinstance(encounter['Id'], dict) else encounter['Id']


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    existing = {}
    for encounter in doc['Encounters']:
        if enc_id(encounter) in REBUILD:
            continue
        for enemy in encounter['Enemies']:
            # 组合槽（`Candidates`）没有 `Id` —— 跳过。
            if 'Id' not in enemy:
                continue
            existing.setdefault(enemy['Id'], enemy)

    def enemy_of(monster_id, position, max_health=None, starting_block=None):
        source = existing[monster_id]
        row = {k: v for k, v in source.items()
               if k not in ('Position', 'StartingBlock')}
        row['Position'] = position
        if max_health is not None:
            row['MaxHealth'] = max_health
        if starting_block is not None:
            row['StartingBlock'] = starting_block
        # 键序与既有记录一致即可（`Position` 之类的位置不影响语义，但保持可读）。
        return row

    def encounter(encounter_id, enemies):
        return {
            'Id': {'Value': encounter_id},
            'Enemies': enemies,
            'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        }

    fresh = [
        encounter('enc_chosen_and_byrd', [enemy_of('chosen', 0), enemy_of('byrd', 1)]),
        encounter('enc_cultist_and_chosen', [enemy_of('cultist', 0), enemy_of('chosen', 1)]),
        encounter('enc_three_cultists', [enemy_of('cultist', None), enemy_of('cultist', None),
                                         enemy_of('cultist', None)]),
        encounter('enc_parasite_and_fungi',
                  [enemy_of('shelled_parasite', 0), enemy_of('fungi_beast', 1)]),
    ]
    doc['Encounters'] = [e for e in doc['Encounters'] if enc_id(e) not in REBUILD] + fresh
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('rebuilt %d encounters from existing records' % len(fresh))


main()
