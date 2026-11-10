"""§328 审计（第二遍）：覆盖面。

第一遍只比"wiki 有 `{{Asc|N|`、内容缺这一档"的动作，条件是**名字对得上**。所以还要问三件事：

1. 哪些怪物**没有** wiki 快照（`native/wiki_asc/<monster>.txt` 不存在）⇒ 它们的升档无从核对；
2. 哪些动作**没在 wiki 行里找到**（`NameKey` 与 wiki 的 `| Name =` 对不上）⇒ 名字一漂，
   第一遍就静默跳过；
3. 哪些带 `ProgramAsc` 的动作**没被检查器的清单钉住**（`INV_ASC_VARIANTS` 里没有）⇒
   值漂了没人红。
"""

import io
import json
import os
import re

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECKER = 'native/sts_content_check.py'
WIKI = 'native/wiki_asc'


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def parse_names(path):
    text = io.open(path, encoding='utf-8').read()
    return {norm(m) for m in re.findall(r'\|\s*Name\s*=\s*(.+?)\s*$', text, re.M)}


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    checker = io.open(CHECKER, encoding='utf-8').read()

    monsters = sorted({a['Id'].split('.')[0] for a in doc['EnemyActions']})
    no_dump = [m for m in monsters if not os.path.exists(os.path.join(WIKI, m + '.txt'))]
    print('怪物 %d 个，缺 wiki 快照 %d 个：%s' % (len(monsters), len(no_dump), no_dump))

    unmatched = []
    for action in doc['EnemyActions']:
        monster = action['Id'].split('.')[0]
        path = os.path.join(WIKI, monster + '.txt')
        if not os.path.exists(path):
            continue
        names = parse_names(path)
        name = action.get('NameKey') or action['Id'].split('.', 1)[1]
        if norm(name) not in names:
            unmatched.append((action['Id'], name))
    print('动作 %d 条，wiki 行里找不到同名 %d 条：' % (len(doc['EnemyActions']), len(unmatched)))
    for action_id, name in unmatched:
        print('   %-34s NameKey=%r' % (action_id, name))

    with_asc = [a for a in doc['EnemyActions'] if a.get('ProgramAsc')]
    unpinned = [a['Id'] for a in with_asc if "'%s':" % a['Id'] not in checker]
    print('带 ProgramAsc 的动作 %d 条，检查器清单没钉 %d 条：%s'
          % (len(with_asc), len(unpinned), unpinned))


main()
