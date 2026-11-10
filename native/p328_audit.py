"""§328 审计：wiki 快照里有 `{{Asc|N|…}}`、而内容里没有对应 `ProgramAsc` 行的动作。

做法（全部是**文本对账**，不猜）：
1. 从 `native/wiki_asc/<monster>.txt` 抽出意图表行：`| Name = X` … `| Effect = …`；
2. 把动作 id 的**前缀**当怪物 id（`book_of_stabbing.multi_stab` → `book_of_stabbing`），
   用 `NameKey` 找到那一行（名字去空格、小写比较）；
3. 数 Effect 里的 `{{Asc|N|` 等级集合，与内容 `ProgramAsc` 的 `AscensionMin` 集合比；
4. 打印**缺哪一档**，并打印 wiki 的 Effect 原文供人核对。

只报告，不改任何东西。
"""

import io
import json
import os
import re

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
WIKI = 'native/wiki_asc'

ASC_RE = re.compile(r'\{\{Asc\|(\d+)\|')


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def parse_rows(path):
    """`| Name = X` 后面跟 `| Effect = …`（可能跨行，用 `}}` 收尾）。"""
    rows = {}
    text = io.open(path, encoding='utf-8').read()
    current = None
    for line in text.splitlines():
        m = re.match(r'\|\s*Name\s*=\s*(.+?)\s*$', line)
        if m:
            current = norm(m.group(1))
            rows.setdefault(current, '')
            continue
        if current is None:
            continue
        m = re.match(r'\|\s*Effect\s*=\s*(.*)$', line)
        if m:
            rows[current] = m.group(1)
    return rows


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    rows_cache = {}

    def rows_for(monster):
        if monster not in rows_cache:
            path = os.path.join(WIKI, monster + '.txt')
            rows_cache[monster] = parse_rows(path) if os.path.exists(path) else None
        return rows_cache[monster]

    missing = []
    for action in doc['EnemyActions']:
        action_id = action['Id']
        monster = action_id.split('.')[0]
        rows = rows_for(monster)
        if rows is None:
            continue
        name = action.get('NameKey') or action_id.split('.', 1)[1]
        effect = rows.get(norm(name))
        if effect is None:
            continue
        wiki_levels = sorted({int(x) for x in ASC_RE.findall(effect)})
        if not wiki_levels:
            continue
        have = sorted({int(r['AscensionMin']) for r in (action.get('ProgramAsc') or [])})
        if set(wiki_levels) - set(have):
            missing.append((action_id, wiki_levels, have, effect.strip()[:150]))

    print('动作总数 %d；wiki 有升档而内容缺档：%d' % (len(doc['EnemyActions']), len(missing)))
    for action_id, wiki_levels, have, effect in missing:
        print('  %-32s wiki=%-10s content=%-10s %s'
              % (action_id, wiki_levels, have, effect))


main()
