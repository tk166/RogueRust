"""构建两份生成物：

1. `web-next/src/i18n/zh.ts` —— 内容 id → 中文名/介绍。
2. `web-next/src/view/cardMeta.ts` —— 卡牌的**种类**与**要不要玩家选目标**。

## 中文的来源（两个，互相核对）

1. **spire-archive**（`https://spire-archive.com/api/sts1/...`）—— 从游戏文件解析、13 种语言。
   主来源（机器可读、可复现）。
2. **仓库自己的 `sts/content/*.json`** —— 早先里程碑写的中文，用来交叉核对。两边都有的 id 里
   有 8 处不一致（都是仓库里的旧中文**缩写**：铁斩/铁斩波、顺劈/顺劈斩…），以官方名为准；
   `sts.huijiwiki.com` 的抽查（铁斩波 = Iron Wave）也站在 spire-archive 一边。

## 卡牌元数据的来源（**不猜**）

* **种类**：`Cards[].Tags` 里有 attack / skill / power / status / curse。
* **要不要玩家选目标**：卡牌程序里有没有 `sel.eventTarget`（"作用于被选中的那个目标"）。
  ⚠️ 这是第十四轮 Review P1-A 的正解：内核**故意**为"每张可出的牌 × 每个活敌人"各发一条动作
  （它无法廉价判断这张牌是不是定向牌），所以**动作表的 `targetSlot` 不是卡牌的目标声明**。
  与 `sts/content/cards.json` 里显式的 `target` 字段对拍：10/10 一致。

## 已知不精确

`upgrade.description` 在 spire-archive 里**只有英文**，所以 `+` 变体的介绍沿用基础文本、名字加 `+`。

## 缓存

抓下来的原文存在 `native/zh_source/`，**入库** ⇒ 构建默认读缓存，闸门不需要网络。
要更新就 `python native/build_zh_i18n.py --refresh`。
"""

import io
import json
import os
import sys
import urllib.request

from zh_events import build_events

NL = chr(10)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'native', 'zh_source')
CONTENT = os.path.join(ROOT, 'tools', 'contentc', 'packages', 'sts', 'sts.roguedeck.json')
LEGACY = os.path.join(ROOT, 'sts', 'content')
OUT = os.path.join(ROOT, 'web-next', 'src', 'i18n', 'zh.ts')
META_OUT = os.path.join(ROOT, 'web-next', 'src', 'view', 'cardMeta.ts')
API = 'https://spire-archive.com/api/sts1/%s?lang=%s&limit=500'
TABLES = ('cards', 'relics', 'potions', 'monsters')

os.makedirs(CACHE, exist_ok=True)


def fetch(table, lang):
    """读缓存；`--refresh` 时重抓。"""
    path = os.path.join(CACHE, '%s.%s.json' % (table, lang))
    if '--refresh' not in sys.argv and os.path.exists(path):
        return json.load(io.open(path, encoding='utf-8'))
    proxy = os.environ.get('HTTPS_PROXY', '')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy}))
    opener.addheaders = [('User-Agent', 'Mozilla/5.0'), ('Accept', 'application/json')]
    payload = json.loads(opener.open(API % (table, lang), timeout=90).read().decode('utf-8'))
    io.open(path, 'w', encoding='utf-8', newline=NL).write(
        json.dumps(payload, ensure_ascii=False, indent=1) + NL
    )
    print('  fetched %s.%s (%d items)' % (table, lang, len(payload['items'])))
    return payload


def normalise(id_text):
    """内容 id 与 API id 的桥：`attack_potion` ↔ `ATTACKPOTION`。"""
    return id_text.replace('_', '').upper()


def write_module(path, header_lines, body_lines, tail_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = NL.join(header_lines + body_lines + tail_lines) + NL
    io.open(path, 'w', encoding='utf-8', newline=NL).write(text)


def main():
    print('读取内容镜像的 id …')
    content = json.load(io.open(CONTENT, encoding='utf-8'))

    tables = {}
    for table in TABLES:
        zh = fetch(table, 'zh')
        en = fetch(table, 'en')
        # ⚠️ en / zh 两个列表的**顺序不一致**（实测 relics 与 monsters 都错位），所以按 id join。
        tables[table] = ({item['id']: item for item in zh['items']},
                         {item['id']: item for item in en['items']})

    out = {
        'note': '内容 id → 中文名/介绍。由 native/build_zh_i18n.py 生成，不要手改。',
        'source': 'spire-archive.com/api/sts1 (lang=zh/en) + sts/content/*.json',
        'cards': {},
        'relics': {},
        'potions': {},
        'monsters': {},
        'statuses': {},
        'events': {},
        'eventLabels': {},
    }
    problems = []

    # ── 卡牌：先按英文名 join（内容给的是 NameKey），失败再按 id ──────────────────
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

    def pick_card_by_id(card_id):
        base = card_id.rstrip('+')
        upper = base.upper()
        for candidate in (upper + '_R', upper, normalise(base) + '_R', normalise(base)):
            if candidate in cards_zh:
                return cards_zh[candidate]
        return None

    upgraded_with_base_text = 0
    for card in content['Cards']:
        card_id = card['Id']
        name_key = card.get('NameKey') or ''
        plus_count = len(card_id) - len(card_id.rstrip('+'))
        item = pick_card(name_key.rstrip('+')) or pick_card_by_id(card_id) or pick_card_by_id(name_key)
        if item is None:
            problems.append('card %s (NameKey=%r) 没有中文条目' % (card_id, name_key))
            continue
        if plus_count > 0:
            upgraded_with_base_text += 1
        out['cards'][card_id] = {
            'name': item['name'] + ('+' * plus_count),
            'text': (item.get('description') or '').strip(),
        }

    # ── 遗物 / 药水 / 怪物：按 id join ─────────────────────────────────────────
    def fill(section, items, label):
        zh_by_id = tables[section][0]
        by_norm = {normalise(item_id): item for item_id, item in zh_by_id.items()}
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

    # ── 状态：spire-archive 的 powers 只有英文 ⇒ 用仓库自己的中文 ────────────────
    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = {'name': legacy[axis]}
    for status_id, name in legacy.items():
        out['statuses'].setdefault(status_id, {'name': name})
    print('  %-9s %3d/%3d 有中文（缺 %d）' % (
        '状态', len(out['statuses']), len(content['Statuses']),
        max(0, len(content['Statuses']) - len(out['statuses']))))
    print('  %-9s %3d/%3d 有中文（缺 %d）' % (
        '卡牌', len(out['cards']), len(content['Cards']), len(problems)))

    # ── 交叉核对：两边都有的中文名必须一致 ────────────────────────────────────
    mismatches = []
    for legacy_file, section in (('cards.json', 'cards'), ('enemies.json', 'monsters'),
                                 ('relics.json', 'relics')):
        path = os.path.join(LEGACY, legacy_file)
        if not os.path.exists(path):
            continue
        for item in json.load(io.open(path, encoding='utf-8')):
            mine = out[section].get(item['id'])
            if mine and mine['name'] != item['name']:
                mismatches.append('%s: 仓库=%r spire-archive=%r'
                                  % (item['id'], item['name'], mine['name']))
    if mismatches:
        print(NL + '⚠️ 两个来源不一致（%d 条，以官方名为准）：' % len(mismatches))
        for line in mismatches:
            print('   ', line)
    else:
        print(NL + '交叉核对：仓库中文与 spire-archive 一致')

    if problems:
        print(NL + '⚠️ 没有中文条目的卡牌（%d 条）：' % len(problems))
        for line in problems[:12]:
            print('   ', line)

    out['upgradedWithBaseText'] = upgraded_with_base_text

    # ── 事件：名字/正文/根选项来自 spire-archive（官方 13 语言），id 对照见 `zh_events.py` ──
    events, event_labels, event_stats = build_events(content)
    out['events'] = events
    out['eventLabels'] = event_labels
    print('  事件       %3d 个（有名字 %d、有正文 %d、根选项 %d 条、标签 %d 条）' % (
        event_stats['roots'], event_stats['named'], event_stats['text'],
        event_stats['options'], len(event_labels)))
    if event_stats['missing']:
        print('    缺名字：', ', '.join(event_stats['missing']))
    if event_stats['optionMismatch']:
        print('    根选项条数不一致（按标签表回退）：',
              ', '.join('%s %d/%d' % row for row in event_stats['optionMismatch']))

    # ── 卡牌元数据：种类（Tags）+ 要不要目标（Program 的 sel.eventTarget）────────
    meta = {}
    for card in content['Cards']:
        tags = [tag.get('value') for tag in (card.get('Tags') or [])]
        kind = next((tag for tag in ('attack', 'skill', 'power', 'status', 'curse')
                     if tag in tags), 'skill')
        program = (json.dumps(card.get('Program'), ensure_ascii=False)
                   + json.dumps(card.get('LifecyclePrograms'), ensure_ascii=False))
        meta[card['Id']] = {
            'kind': kind,
            'targeting': 'singleEnemy' if 'sel.eventTarget' in program else 'none',
        }
    print('  元数据     %3d 张（要目标 %d）' % (
        len(meta), sum(1 for row in meta.values() if row['targeting'] == 'singleEnemy')))

    write_module(
        META_OUT,
        [
            '// 生成物：`python native/build_zh_i18n.py` 重建，**不要手改**。',
            '//',
            '// 「种类」与「要不要玩家选目标」都来自内容包（`Cards[].Tags` + 程序里的 `sel.eventTarget`）。',
            '// ⚠️ **不从动作表的 targetSlot 反推**：内核故意为"每张可出的牌 × 每个活敌人"各发一条',
            '// 动作（它无法廉价判断定向性），那是**枚举策略**，不是卡牌语义（第十四轮 Review P1-A）。',
            '',
            'export interface CardMeta {',
            '  readonly kind: "attack" | "skill" | "power" | "status" | "curse";',
            '  readonly targeting: "none" | "singleEnemy";',
            '}',
            '',
        ],
        ['const cardMeta: Record<string, CardMeta> = '
         + json.dumps(meta, ensure_ascii=False, indent=1) + ';'],
        ['', 'export default cardMeta;'],
    )

    write_module(
        OUT,
        [
            '// 生成物：`python native/build_zh_i18n.py` 重建，**不要手改**。',
            '// 来源：spire-archive.com/api/sts1（lang=zh/en）+ `sts/content/*.json`（交叉核对）。',
            '',
        ],
        ['const zh = ' + json.dumps(out, ensure_ascii=False, indent=1) + ';'],
        ['', 'export default zh;'],
    )

    total = sum(len(out[key]) for key in ('cards', 'relics', 'potions', 'monsters', 'statuses', 'events'))
    print(NL + '写出 %s（%d 条；+ 变体沿用基础文本 %d 条）' % (
        os.path.relpath(OUT, ROOT), total, upgraded_with_base_text))
    print('写出 %s（%d 张）' % (os.path.relpath(META_OUT, ROOT), len(meta)))


if __name__ == '__main__':
    main()
