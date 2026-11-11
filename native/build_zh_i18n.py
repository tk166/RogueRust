"""构建 `web-next/src/i18n/zh.json`：内容 id → 中文名/介绍。

## 数据来源（两个，互相核对）

1. **spire-archive**（`https://spire-archive.com/api/sts1/...`）—— 从游戏文件解析、13 种语言，
   卡牌/遗物/药水/怪物都有中文。**这是主来源**（机器可读、可复现）。
2. **仓库自己的 `sts/content/*.json`** —— 早先里程碑写的中文（12 卡 / 5 敌 / 8 状态 / 5 遗物）。
   用来做**交叉核对**：两边都有的 id，名字必须一致，不一致就打印出来（不静默选一个）。

另：`sts.huijiwiki.com`（灰机中文 wiki）被 Cloudflare 挡，只能靠 `web_search` 的 snippet 逐条取，
所以没走它；抽查过两条（`铁斩波` = Iron Wave、`打击` = Strike）与 spire-archive 一致。

## 已知不精确

`upgrade.description` 在 spire-archive 里**只有英文**（本地化数据里升级描述没进 API），
所以 `+` 变体的介绍**沿用基础文本**、名字加 `+`。闸门会统计有多少条 `+` 是这种情形。

## 缓存

抓下来的原文存在 `native/zh_source/`，**入库**。构建默认读缓存 ⇒ 闸门不需要网络；
要更新就 `python native/build_zh_i18n.py --refresh`。
"""

import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'native', 'zh_source')
CONTENT = os.path.join(ROOT, 'tools', 'contentc', 'packages', 'sts', 'sts.roguedeck.json')
LEGACY = os.path.join(ROOT, 'sts', 'content')
# ⚠️ 输出成 `.ts` 而不是 `.json`：闸门 27 把源码**直接编译成 ESM** 跑，Node 的 ESM 要求 JSON
# import 带 attribute（with { type: 'json' }），而 TS/Vite 又不需要 —— 用 .ts 一次抹平两边差异，
# 顺带拿到类型检查。
OUT = os.path.join(ROOT, 'web-next', 'src', 'i18n', 'zh.ts')
API = 'https://spire-archive.com/api/sts1/%s?lang=%s&limit=500'
TABLES = ('cards', 'relics', 'potions', 'monsters')

os.makedirs(CACHE, exist_ok=True)


def fetch(table, lang):
    """读缓存；`--refresh` 时重抓。缓存入库 ⇒ 闸门不联网。"""
    path = os.path.join(CACHE, '%s.%s.json' % (table, lang))
    if '--refresh' not in sys.argv and os.path.exists(path):
        return json.load(io.open(path, encoding='utf-8'))
    proxy = os.environ.get('HTTPS_PROXY', '')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy}))
    opener.addheaders = [('User-Agent', 'Mozilla/5.0'), ('Accept', 'application/json')]
    payload = json.loads(opener.open(API % (table, lang), timeout=90).read().decode('utf-8'))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(payload, ensure_ascii=False, indent=1) + '\n'
    )
    print('  fetched %s.%s (%d items)' % (table, lang, len(payload['items'])))
    return payload


def normalise(id_text):
    """内容 id 与 API id 的桥：`attack_potion` ↔ `ATTACKPOTION`。"""
    return id_text.replace('_', '').upper()


def main():
    print('读取内容镜像的 id …')
    content = json.load(io.open(CONTENT, encoding='utf-8'))

    tables = {}
    for table in TABLES:
        zh = fetch(table, 'zh')
        en = fetch(table, 'en')
        en_by_id = {item['id']: item for item in en['items']}
        # ⚠️ en / zh 两个列表的**顺序不一致**（实测 relics 与 monsters 都错位），所以按 id join。
        zh_by_id = {item['id']: item for item in zh['items']}
        tables[table] = (zh_by_id, en_by_id)

    out = {
        'note': '内容 id → 中文名/介绍。由 native/build_zh_i18n.py 生成，不要手改。',
        'source': 'spire-archive.com/api/sts1 (lang=zh/en) + sts/content/*.json',
        'cards': {},
        'relics': {},
        'potions': {},
        'monsters': {},
        'statuses': {},
    }
    problems = []

    # ── 卡牌：按**英文名**join（内容给的是 NameKey），同名多色时挑铁甲战士 ──────────
    cards_zh, cards_en = tables['cards']
    by_en = {}
    for item_id, zh_item in cards_zh.items():
        en_item = cards_en.get(item_id)
        if not en_item:
            continue
        by_en.setdefault(en_item['name'], []).append(zh_item)

    def pick_card(en_name):
        candidates = by_en.get(en_name)
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.get('color') == 'ironclad':
                return candidate
        return candidates[0]

    # 按 id 索引（API 的 id 是 `STRIKE_R` / `IRON_WAVE` 这种大写）
    by_id = dict(cards_zh)

    def pick_card_by_id(card_id):
        base = card_id.rstrip('+')
        upper = base.upper()
        for candidate in (upper + '_R', upper, normalise(base) + '_R', normalise(base)):
            if candidate in by_id:
                return by_id[candidate]
        return None

    upgraded_with_base_text = 0
    for card in content['Cards']:
        card_id = card['Id']
        name_key = card.get('NameKey') or ''
        plus_count = len(card_id) - len(card_id.rstrip('+'))
        upgraded = plus_count > 0
        # ⚠️ 多级 `+`（`searing_blow++` …）要**全部**剥掉再找基础条目。
        base_key = name_key.rstrip('+')
        item = pick_card(base_key)
        if item is None:
            # 有些 `NameKey` 直接就是小写 id（`omega` / `panache` / `the_bomb`）⇒ 按 id 找。
            item = pick_card_by_id(card_id)
        if item is None:
            # 最后一条：把 NameKey 当 id 试（下划线 → 大写）。
            item = pick_card_by_id(name_key)
        if item is None:
            problems.append('card %s (NameKey=%r) 没有中文条目' % (card_id, name_key))
            continue
        text = (item.get('description') or '').strip()
        if upgraded:
            upgraded_with_base_text += 1
        out['cards'][card_id] = {
            'name': item['name'] + ('+' * plus_count),
            'text': text,
        }

    # ── 遗物 / 药水 / 怪物：按 id join ─────────────────────────────────────────
    def fill(section, items, label):
        zh_by_id, en_by_id = tables[section]
        by_norm = {}
        for item_id, item in zh_by_id.items():
            by_norm[normalise(item_id)] = item
        missing = 0
        for entity in items:
            entity_id = entity['Id']
            item = zh_by_id.get(entity_id.upper()) or by_norm.get(normalise(entity_id))
            if item is None:
                missing += 1
                continue
            entry = {'name': item['name']}
            if item.get('description'):
                entry['text'] = item['description'].strip()
            out[section][entity_id] = entry
        print('  %-9s %3d/%3d 有中文（缺 %d）' % (label, len(items) - missing, len(items), missing))

    fill('relics', content['Relics'], '遗物')
    fill('potions', content['Potions'], '药水')
    fill('monsters', content['Monsters'], '怪物')

    # ── 状态：spire-archive 的 powers 只有英文 ⇒ 用仓库自己的中文，缺的留空 ──────
    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    # ABI 五轴的 id 是 `standard.*`，仓库里的是裸 id
    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = {'name': legacy[axis]}
    for status_id, name in legacy.items():
        out['statuses'].setdefault(status_id, {'name': name})
    print('  %-9s %3d/%3d 有中文（缺 %d）' % (
        '状态', len(out['statuses']), len(content['Statuses']),
        max(0, len(content['Statuses']) - len(out['statuses']))))

    # ── 交叉核对：两边都有的卡名必须一致 ─────────────────────────────────────
    mismatches = []
    for legacy_file, section in (('cards.json', 'cards'), ('enemies.json', 'monsters'),
                                 ('relics.json', 'relics')):
        path = os.path.join(LEGACY, legacy_file)
        if not os.path.exists(path):
            continue
        for item in json.load(io.open(path, encoding='utf-8')):
            mine = out[section].get(item['id'])
            if mine and mine['name'] != item['name']:
                mismatches.append('%s: 仓库=%r spire-archive=%r' % (item['id'], item['name'], mine['name']))
    if mismatches:
        print('\n⚠️ 两个来源不一致（%d 条）：' % len(mismatches))
        for line in mismatches:
            print('   ', line)
    else:
        print('\n交叉核对：仓库中文与 spire-archive 一致')

    if problems:
        print('\n⚠️ 没有中文条目的卡牌（%d 条）：' % len(problems))
        for line in problems[:20]:
            print('   ', line)

    out['upgradedWithBaseText'] = upgraded_with_base_text
    print('  %-9s %3d/%3d 有中文（缺 %d）' % (
        '卡牌', len(out['cards']), len(content['Cards']), len(problems)))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    body = json.dumps(out, ensure_ascii=False, indent=1)
    header = (
        '// 生成物：python native/build_zh_i18n.py 重建，不要手改。\n'
        '// 来源：spire-archive.com/api/sts1（lang=zh/en）+ sts/content/*.json（交叉核对）。\n'
    )
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(
        header + 'const zh = ' + body + ';\n\nexport default zh;\n'
    )
    total = sum(len(out[key]) for key in ('cards', 'relics', 'potions', 'monsters', 'statuses'))
    print('\n写出 %s（%d 条；+ 变体沿用基础文本 %d 条）' % (
        os.path.relpath(OUT, ROOT), total, upgraded_with_base_text))


if __name__ == '__main__':
    main()
