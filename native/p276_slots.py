"""§276 第一部分：内容门里那个**过期的** `MAX_ENEMIES_IN_FIGHT` 镜像 + 解锁 `Swarm of Slimes`。

## 先纠正一处"两个数不一致"

`native/sts_content_check.py` 的镜像是 **4**，而内核
（`rd_core::state::MAX_ENEMIES_IN_FIGHT`）与画面（`rd-wasm::MAX_ENEMY_SLOTS`）都已经是 **6**
（§257 为 Reptomancer 的四把匕首涨的）。也就是说：**能力早就有，只有闸门在原地**。
所以这一节不用抬常量，只要把镜像对齐 —— 然后 `Swarm of Slimes`（5 个敌人）就能进场。

⚠️ 这正是"同一个词表被两处认识就一定漂"的实例：镜像常量没跟着涨，于是"内核能跑"的东西
被闸门挡住，而**闸门报的是内容的错**。三个数（内核 / 画面 / 闸门）现在都是 6。
"""
import copy
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

SWARM = 'enc_swarm_of_slimes'
SPIKE_S = ('spike_slime_s', 10, 11)
ACID_S = ('acid_slime_s', 8, 9)

MIRROR_OLD = '''MAX_ENEMIES_IN_FIGHT = 4'''
MIRROR_NEW = '''# ⚠️ §276：这里曾经是 4，而内核与画面在 §257 就涨到了 6（Reptomancer 的四把匕首）。
# 镜像没跟着涨 ⇒ "内核能跑"的 `Swarm of Slimes`（5 个敌人）被闸门挡住，而**闸门报的是内容的错**。
# 现在两边都是 6；`rd-wasm::MAX_ENEMY_SLOTS` 也是 6，三个数是同一个。
MAX_ENEMIES_IN_FIGHT = 6'''


def main():
    check = io.open(CHECK, encoding='utf-8').read()
    if MIRROR_OLD in check:
        check = check.replace(MIRROR_OLD, MIRROR_NEW, 1)
        print('gate mirror: 4 -> 6')
    else:
        assert 'MAX_ENEMIES_IN_FIGHT = 6' in check, 'neither 4 nor 6?'
        print('gate mirror: already 6')

    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']
    present = SWARM in {ids(row) for row in doc['Encounters']}
    if not present:
        template = {}
        for encounter in doc['Encounters']:
            for enemy in encounter['Enemies']:
                template.setdefault(enemy['Id'], enemy)
        # `acid_slime_s` **没有**既有遭遇行（此前只有 roster 行）⇒ 从 roster 造一份。
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

        enemies = []
        specs = [SPIKE_S, SPIKE_S, SPIKE_S, ACID_S, ACID_S]
        for position, (mid, hp, asc_hp) in enumerate(specs):
            row = copy.deepcopy(template[mid])
            row['MaxHealth'] = hp
            row['MaxHealthAsc'] = [{'AscensionMin': 7, 'MaxHealth': asc_hp}]
            row['Position'] = position
            enemies.append(row)
        doc['Encounters'].append({
            'Id': {'Value': SWARM},
            'Enemies': enemies,
            'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        })
        # 权重：wiki 是 1（最稀的一档）⇒ 7。
        doc['EncounterTables']['Weak'].append({'Id': SWARM, 'Weight': 7})
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        print('encounter %s: %d enemies; Weak pool %d' % (
            SWARM, len(enemies), len(doc['EncounterTables']['Weak'])))
    else:
        print('encounter %s: already present' % SWARM)

    # ---- 闸门三张表（幂等）
    check = io.open(CHECK, encoding='utf-8').read()
    if '"enc_swarm_of_slimes"' not in check:
        check = check.replace(
            '''    "enc_blue_slaver": ["blue_slaver"],
}''',
            '''    "enc_blue_slaver": ["blue_slaver"],
    # §276: `Swarm of Slimes` —— 3× Spike (S) + 2× Acid (S)。内容里**第一个 5 敌人**的遭遇，
    # 也是 `acid_slime_s` 第一次真正上场（此前只有 roster 行、没有遭遇用到它）。
    "enc_swarm_of_slimes": ["spike_slime_s", "spike_slime_s", "spike_slime_s",
                            "acid_slime_s", "acid_slime_s"],
}''', 1)
        check = check.replace(
            '''             "enc_three_louses", "enc_two_fungi_beasts", "enc_blue_slaver"],''',
            '''             "enc_three_louses", "enc_two_fungi_beasts", "enc_blue_slaver",
             # §276：5 个敌人 —— 镜像对齐到 6 之后才允许进场。
             "enc_swarm_of_slimes"],''', 1)
        print('gate tables updated')
    else:
        print('gate tables: already present')
    if '    "encounters": 38,' in check:
        check = check.replace('    "encounters": 38,', '    "encounters": 39,', 1)
        print('gate count: 38 -> 39')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(check)


main()
