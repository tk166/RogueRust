"""§257 收尾：把名册（`MON`）的改动同步进遭遇行（`ENCT`），并修 `asc` 清单。

内容门的两条纪律在这里同时起作用：
* `MON` 与 `ENCT` 是**同一份数据的两个副本**，哪一边改了另一边没改 ⇒ 门报
  `Actions/IntentRules/StartingStatuses differs from the roster`；
* `asc` 清单是**手抄的期望值**，所以阈值一改它立刻红 —— 这次红的正是我们要改的那五条。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

SYNC_FIELDS = ('Actions', 'StartingStatuses', 'IntentRules', 'Counters')


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    monsters = {row['Id']: row for row in doc['Monsters']}

    # 1) `lagavulin.stunned` 必须是一行 `EACT`（内核的动作库**就是**这张表）。
    if not any(row['Id'] == 'lagavulin.stunned' for row in doc['EnemyActions']):
        raise SystemExit('lagavulin.stunned missing from EnemyActions — run p257_content.py first')

    # 2) 名册 → 遭遇行
    synced = 0
    for encounter in doc['Encounters']:
        for enemy in encounter['Enemies']:
            roster = monsters.get(enemy['Id'])
            if roster is None:
                continue
            for field in SYNC_FIELDS:
                if field in roster:
                    if enemy.get(field) != roster[field]:
                        enemy[field] = json.loads(json.dumps(roster[field]))
                        synced += 1
                elif field in enemy and not roster.get(field):
                    # 名册没这一格（`Counters: []` 常被省略）⇒ 遭遇行也不要凭空有。
                    enemy.pop(field, None)
                    synced += 1
    print('encounter rows synced: %d field(s)' % synced)

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

    # 3) `asc` 清单：Nemesis / Reptomancer 的阈值从 4/19 改回 3/18。
    src = io.open(CHECK, encoding='utf-8').read()
    replacements = [
        ('"nemesis.tri_attack": [4]', '"nemesis.tri_attack": [3]'),
        ('"nemesis.tri_burn": [19]', '"nemesis.tri_burn": [18]'),
        ('"reptomancer.big_bite": [4]', '"reptomancer.big_bite": [3]'),
        ('"reptomancer.snake_strike": [4]', '"reptomancer.snake_strike": [3]'),
        ('"reptomancer.spawn_dagger": [19]', '"reptomancer.spawn_dagger": [18]'),
    ]
    for old, new in replacements:
        if old in src:
            assert src.count(old) == 1, old
            src = src.replace(old, new)
            print('asc list: %s' % new)
        elif new not in src:
            raise SystemExit('neither %r nor %r in the asc list' % (old, new))
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)


main()
