"""§331 Phase 2（内容）：`N'loth`。

wiki（`slaythespire.wiki.gg/wiki/N'loth`）：

> N'loth is a shrine Event found exclusively in **Act 2**. It will only appear if the player has
> **at least 2 Relics**. This Event is the only way to obtain N'loth's Gift.
>
> "Relic A" and "Relic B" will be **randomly chosen from the player's currently held Relics**.
> `[Offer: Relic A]` **Lose this relic.** Obtain a special relic.

所以内容是这样写的：

* `EventTables.Events2` 一行 + `Requires: relic_count at_least 2`（事件级条件，§331 Phase 1）；
* `EVND` 节点 `nloth`，`RelicOffer: 2`（开事件那一刻掷两件候选）；
* 两个选项的标签是 `Offer: {0}` / `Offer: {1}`（ABI 把 `{n}` 换成那件遗物的显示名），
  效果是 `relic_lose:@0` / `relic_lose:@1`（`@n` = 第 n 件候选）+ `relic:nloths_gift`；
* `[Leave]` 什么都不做。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

doc = json.load(io.open(CONTENT, encoding='utf-8'))

# ── 1. 节点 ───────────────────────────────────────────────────────────────────
assert not any(n['Id'] == 'nloth' for n in doc['EventNodes']), 'nloth already present'
doc['EventNodes'].append({
    'Id': 'nloth',
    'TextKey': ("An odd creature with a hunched back sprouting several tentacles is scrounging "
                "through a pile of trash and debris in front of you. As you approach, he shuffles "
                "towards you in a non-threatening manner. \"N'loth hungry. Feed N'loth.\""),
    'RelicOffer': 2,
    'Options': [
        {
            'Label': 'Offer: {0}',
            'Effects': [
                {'Effect': 'relic_lose:@0', 'Amount': 0},
                {'Effect': 'relic:nloths_gift', 'Amount': 0},
            ],
            'Next': '',
        },
        {
            'Label': 'Offer: {1}',
            'Effects': [
                {'Effect': 'relic_lose:@1', 'Amount': 0},
                {'Effect': 'relic:nloths_gift', 'Amount': 0},
            ],
            'Next': '',
        },
        {
            'Label': 'Leave',
            'Effects': [{'Effect': 'nothing', 'Amount': 0}],
            'Next': '',
        },
    ],
})
print('node nloth added')

# ── 2. 池子（Act 2）+ 事件级条件 ──────────────────────────────────────────────
pool = doc['EventTables']['Events2']
assert not any(r['Id'] == 'nloth' for r in pool), 'nloth already in the pool'
pool.append({
    'Id': 'nloth',
    'Requires': [{'Kind': 'relic_count', 'Op': 'at_least', 'Amount': 2}],
})
print('EventTables.Events2 + nloth (Requires: relic_count >= 2)')

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
print('content written')
