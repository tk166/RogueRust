#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_card_gap.py -- 与 wiki 的**卡表**逐张对账：我们有哪些、缺哪些。

WHY
---
`docs/sts-wiki-gap.md` 里"卡牌缺口"这一节一直是人写的，于是它只会变陈旧：§218–§233 这十几轮
加了 60 多行卡，文档里的数字还停在 51 行。`native/gap_check.py` 解决了"我们有多少"那一半，
但**缺口**是"A 减 B"，B（wiki 那一侧）必须来自网上的真表 —— 所以这个脚本去 wiki 拉。

数据来源（一次请求拿全表，不是逐页抓）：
    https://slaythespire.wiki.gg/api.php?action=cargoquery&tables=Cards
`Module:Cards` 是个 Lua + Cargo 的模块页，真正的数据在 Cargo 表里；`?action=raw` 抓不到，
`action=cargoquery` 可以（`Category:Cards` 也行，但要翻页且混着 `Slay the Spire 2:` 页面）。

用法：
    python -X utf8 native/audit_card_gap.py            # 打印分组缺口
    python -X utf8 native/audit_card_gap.py --write    # 同时写 native/wiki_card_index.json
    python -X utf8 native/audit_card_gap.py --offline  # 只读本地索引（CI/无网时用）

口径（三件事先说清楚，否则"缺 40 张"会被读成"我们做砸了"）：
  * **StS2 的行一律剔除**（`Slay the Spire 2:` 前缀，且它们的 Color 是职业名而不是 Red/Green/…）；
  * `Color` 是 wiki 自己的字段：Red=铁甲战士、Green=静默猎手、Blue=故障机器人、Purple=观者、
    Colorless=无色、Curse=诅咒、Status=状态。**本内容的范围是 Red + Colorless + Curse + Status**
    （起始牌组是铁甲战士），所以其它颜色只统计、不算缺口；
  * id 归一是 `Name.lower().replace(" ", "_").replace("'", "")`，与内容里的写法一致
    （`Strike (Ironclad)` / `Defend (Ironclad)` 这两页是消歧页，单独映射到 `strike` / `defend`）。
"""

import argparse
import io
import json
import os
import urllib.parse
import urllib.request

PROXY = 'http://127.0.0.1:7897'
API = 'https://slaythespire.wiki.gg/api.php?action=cargoquery&format=json&limit=500'
QUERY = '&tables=Cards&fields=_pageName=Page,Name,Color,Type,Rarity,Cost'
INDEX = os.path.join('native', 'wiki_card_index.json')
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

# 本内容的范围：铁甲战士 + 无色 + 诅咒 + 状态。
# §255：观者也纳入范围（§254 决定：`Wish` 落地之后紫卡就算）。
# 代价是诚实的：紫色还有一批没做，脚本会把它们列成 missing —— 那比"装作没有这批牌"好。
IN_SCOPE = ('Red', 'Colorless', 'Curse', 'Status', 'Purple')

# 消歧页 → 内容里的 id。名字里带括号的页面在 wiki 上是"同一张牌的不同职业版本"。
SPECIAL = {
    'Strike (Ironclad)': 'strike',
    'Defend (Ironclad)': 'defend',
}


def fetch_rows():
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY}))
    opener.addheaders = [('User-Agent', 'rogue-rust-content-audit/1.0')]
    rows = []
    for offset in (0, 500, 1000):
        url = '%s%s&offset=%d' % (API, QUERY, offset)
        with opener.open(url, timeout=40) as response:
            page = json.load(response)
        batch = page.get('cargoquery', [])
        rows.extend(entry['title'] for entry in batch)
        if len(batch) < 500:
            break
    return rows


def card_id(name):
    return name.lower().replace(' ', '_').replace("'", '')


def load_index(write):
    if write:
        rows = fetch_rows()
        io.open(INDEX, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(rows, ensure_ascii=False, indent=1) + '\n')
        return rows
    if not os.path.isfile(INDEX):
        raise SystemExit('no %s -- run with --write (needs the proxy)' % INDEX)
    return json.loads(io.open(INDEX, encoding='utf-8').read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='re-fetch the wiki table')
    parser.add_argument('--offline', action='store_true', help='read the local index only')
    args = parser.parse_args()

    rows = load_index(args.write)
    sts2 = [row for row in rows if str(row.get('Page', '')).startswith('Slay the Spire 2:')]
    rows = [row for row in rows if row not in sts2]

    content = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {}
    for card in content['Cards']:
        # 多档升级（`searing_blow++++`）里所有的 `+` 都要剥，否则它们会被当成"wiki 上没有的牌"。
        base = card['Id'].rstrip('+')
        have.setdefault(base, card)

    wiki = {}
    for row in rows:
        color = row.get('Color') or '?'
        if color not in IN_SCOPE:
            continue
        wiki[SPECIAL.get(row['Page'], card_id(row['Name']))] = row

    print('wiki rows: %d (StS2 dropped: %d) | in-scope wiki cards: %d | content base cards: %d'
          % (len(rows), len(sts2), len(wiki), len(have)))
    print()

    # 缺口按（颜色, 类型, 稀有度）分组：这是"还差哪些牌"的可执行形状。
    missing = {}
    for cid, row in wiki.items():
        if cid in have:
            continue
        key = (row.get('Color'), row.get('Type'), row.get('Rarity'))
        missing.setdefault(key, []).append(cid)
    for key in sorted(missing):
        print('-- %-9s %-8s %-10s miss %3d | %s'
              % (key[0], key[1], key[2], len(missing[key]), ', '.join(sorted(missing[key]))))
    extra = sorted(cid for cid in have if cid not in wiki)
    print()
    print('in-scope missing: %d   (have %d of %d)'
          % (sum(len(v) for v in missing.values()),
             len(wiki) - sum(len(v) for v in missing.values()), len(wiki)))
    print('content-only (wiki lists them under another color, or they are ours): %s'
          % ', '.join(extra))


main()
