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

#: 只在状态里出现的词 → `(中文名, 中文说明)`（§388 第 ③ 层 + §393）。
#:
#: ⚠️ **只作显示名**：任何规则判定都走 id，不走这里。来源是官方中文本地化；
#: 这些条目没有第二来源核对（不像 wiki 数值那样），所以不写进 `sts-wiki-gap.md` 的账。
STATUS_ZH = {
    'standard.artifact': ('神器', '抵消接下来 N 个负面效果。'),
    'standard.cap_cost_at': ('费用上限', '这张牌的费用被限制在一个上限。'),
    'standard.confusion': ('混乱', '抽到的牌费用随机化。'),
    'standard.constricted': ('紧束', '每回合结束时失去 N 点生命。'),
    'standard.curiosity': ('好奇', '每当你打出一张能力牌，它获得 N 点力量。'),
    'standard.curl_up': ('蜷缩', '第一次受到攻击伤害时，获得 N 点格挡。'),
    'standard.double_damage': ('双倍伤害', '下一张攻击牌打出两次。'),
    'standard.draw_reduction': ('抽牌减少', '每回合少抽 N 张牌。'),
    'standard.enrage': ('激怒', '每当你打出一张技能牌，它获得 N 点力量。'),
    'standard.entangle_ready': ('缠绕就绪', '下一回合缠绕你。'),
    'standard.entangled': ('缠绕', '本回合不能打出攻击牌。'),
    'standard.fading': ('消逝', 'N 回合后消失。'),
    'standard.flying': ('飞行', '受到的攻击伤害减半；被击中 N 次后落地。'),
    'standard.hex': ('诅咒', '每当你打出一张非攻击牌，获得 1 张虚空。'),
    'standard.intangible': ('无形', '受到的伤害降为 1。回合结束时减 1 层。'),
    'standard.lagavulin_asleep': ('沉睡', '沉睡中：N 回合内不行动、也不受伤害。'),
    'standard.lose_dexterity': ('失去敏捷', '回合结束时失去 N 点敏捷。'),
    'standard.lose_strength': ('失去力量', '回合结束时失去 N 点力量。'),
    'standard.malleable': ('可塑', '受到攻击伤害时获得格挡，格挡量逐次增加。'),
    'standard.mode_shift': ('模式转换', '再受到 N 点伤害就切换形态。'),
    'standard.nightmare_pending': ('噩梦待发', '下回合把选中的牌各复制 N 张。'),
    'standard.no_block_from_cards': ('卡牌不提供格挡', '牌给的格挡无效。'),
    'standard.no_draw': ('无法抽牌', '回合开始时不再抽牌。'),
    'standard.omega': ('欧米伽', 'N 回合结束时，对所有敌人造成 50 点伤害。'),
    'standard.painful_stabs': ('痛苦刺击', '每次攻击造成未被格挡的伤害时，塞 1 张伤口。'),
    'standard.phantom_veil': ('幻影面纱', '本回合受到的伤害降为 1。'),
    # ⚠️ 名字里必须带**条件**：玩家看到"分裂"就以为"它这一回合要分裂了"（报障原话：
    # "进来的意图立马是分裂但是实际上并没有分裂"）。带上"生命 ≤50%"之后它读起来是一个**条件**。
    'standard.phase_split': ('分裂（生命 ≤50%）', '生命降到 50% 以下时，分裂成 1 只大型酸液史莱姆和 1 只大型尖刺史莱姆（各带当前生命）。'),
    'standard.plated_armor': ('镀甲', '回合结束时获得 N 点格挡；受到未被格挡的攻击伤害时减 1 层。'),
    'standard.poison': ('中毒', '回合开始时失去 N 点生命，然后层数减 1。'),
    'standard.regain_strength': ('恢复力量', '回合结束时恢复 N 点力量。'),
    'standard.regen': ('再生', '回合结束时回复 N 点生命，然后层数减 1。'),
    'standard.sharp_hide': ('尖刺外壳', '被攻击时对攻击者造成 N 点伤害。'),
    'standard.slow': ('迟缓', '本回合每打出一张牌，受到的伤害 +10%。'),
    'standard.split': ('分裂', '死亡时分裂成两只更小的史莱姆。'),
    'standard.split_acid_l': ('分裂：大型酸液', '死亡时分裂成两只中型酸液史莱姆。'),
    'standard.split_spike_l': ('分裂：大型尖刺', '死亡时分裂成两只中型尖刺史莱姆。'),
    'standard.spore_cloud': ('孢子云', '死亡时给凶手 2 层虚弱。'),
    'standard.stasis': ('停滞', '把你的 1 张牌扣住，之后归还。'),
    'standard.stasis_ready': ('停滞就绪', '下一次停滞会扣住你的牌。'),
    'standard.the_bomb_damage': ('炸弹伤害', 'N 回合后爆炸，造成 40 点伤害。'),
    'standard.time_warp': ('时间扭曲', '本回合每打出 12 张牌，你失去一个回合。'),
    'standard.unawakened': ('未觉醒', '第一次死亡后复活。'),
    'standard.fairy_in_a_bottle': ('瓶中精灵', '死亡时回复 30% 生命并复活（一次性）。'),
    'standard.duplication': ('复制', '下一张打出的牌打出两次。'),
    'standard.the_boot': ('靴子', '小于等于 4 点的攻击伤害提升到 5 点。'),
    'standard.paper_phrog': ('纸蛙', '易伤的层数不会在回合结束时减少。'),
    'standard.paper_krane': ('纸鹤', '虚弱的层数不会在回合结束时减少。'),
    'standard.snecko_skull': ('蛇骷髅', '每场战斗第一次抽到诅咒时，抽 1 张牌。'),
    'standard.duality': ('双重', '每打出一张攻击牌，获得 1 点敏捷。'),
    'standard.energized': ('充能', '获得 N 点额外能量。'),
    'standard.draw_card_next_turn': ('下回合抽牌', '下回合多抽 N 张牌。'),
}
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

    # ── 状态：三条来源，按顺序（§388）────────────────────────────────────────
    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    # §393：legacy 里**本来就有** `desc`（中文说明），生成器以前只搬了名字 ⇒ 悬浮窗没字。
    legacy_text = {item['id']: item.get('desc', '') for item in statuses}
    def legacy_entry(status_id):
        """legacy 的一条 → `{name, text}`（`desc` 缺就只给名字）。"""
        name = legacy[status_id]
        desc = legacy_text.get(status_id, '')
        return {'name': name, 'text': desc} if desc else {'name': name}

    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = legacy_entry(axis)
    for status_id in legacy:
        out['statuses'].setdefault(status_id, legacy_entry(status_id))
        # legacy 表里既有 `thorns` 也有 `standard.thorns` 的键，而运行时查的是**全 id**
        # （`standard.thorns`）⇒ 无前缀的那几条也要登记一份带前缀的别名，否则
        # 屏幕上照样是 `thorns`（§388 的第一版就漏了这一步）。
        if '.' not in status_id:
            out['statuses'].setdefault('standard.' + status_id, legacy_entry(status_id))

    # ② 跨表复用：`standard.X` 的 `X` 在别的表里已经翻译过 ⇒ 用那个名字。
    # 状态与它来源（遗物/卡/药水）本来就是同一个词，两份翻译只会漂。
    reused = 0
    for status in content['Statuses']:
        status_id = status['Id']
        if status_id in out['statuses']:
            continue
        short = status_id.split('.', 1)[1] if '.' in status_id else status_id
        for table in ('relics', 'cards', 'potions', 'monsters'):
            entry = out[table].get(short)
            if entry and entry.get('name'):
                # §393：**说明也一起搬** —— 状态与它来源本来就是同一句话
                # （`orichalcum` 的"没有格挡就获得 6 格挡"就是那条遗物的原文）。
                merged = {'name': entry['name']}
                if entry.get('text'):
                    merged['text'] = entry['text']
                out['statuses'][status_id] = merged
                reused += 1
                break
    # ③ 人工译名（只在状态里出现的词）。来源：官方中文本地化。
    # ⚠️ 这些**只做显示名**，不进任何规则判定（规则一律走 id）。
    for status_id, row in STATUS_ZH.items():
        entry = {'name': row[0]}
        if row[1]:
            entry['text'] = row[1]
        out['statuses'].setdefault(status_id, entry)
    print('  状态复用   %3d 条（跨表）+ %d 条（人工译名表）' % (reused, len(STATUS_ZH)))
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
        # §379：费用与稀有度。三条规则都来自内容包，不猜：
        #   * 能量费 = `Costs[]` 里 `standard.energy` 的 `Amount`；
        #   * `x_cost` 标签 ⇒ "X"（内容里 Amount 是 0，直接显示会变成"0 费"）；
        #   * `unplayable` 标签 ⇒ "-"（诅咒/状态牌，没有可支付的费用）。
        energy = 0
        for cost in card.get('Costs') or []:
            if (cost.get('ResourceId') or {}).get('value') == 'standard.energy':
                energy = cost.get('Amount') or 0
                break
        if 'x_cost' in tags:
            cost = 'X'
        elif 'unplayable' in tags:
            cost = '-'
        else:
            cost = energy
        # §381：**"要不要目标"不能只看 `sel.eventTarget`**。
        #
        # `观察弱点`（`spot_weakness`）的程序是 `conditional{ intent.targetIntendsAttack }`
        # —— 它**间接**读事件目标（"那只敌人的意图是攻击吗"），JSON 里一个 `sel.eventTarget`
        # 都没有。于是旧启发式把它判成"无目标"，界面就把"打向任意敌人"归并成一次无目标出牌：
        # 玩家没选敌人，卡直接结算，条件读到空目标 ⇒ 力量一点没加（玩家实测报的"没有选择敌人
        # 就直接触发了"）。
        #
        # 判据：程序里出现 `sel.eventTarget` **或** `intent.target*`（条件/表达式读事件目标）。
        # 内容里目前只有 `intent.targetIntendsAttack` 一种，但前缀匹配是**穷尽**的
        # （闸门 56 遍历全部卡牌，断言"提到目标 ⇒ 被标成定向"没有遗漏）。
        needs_target = 'sel.eventTarget' in program or 'intent.target' in program
        meta[card['Id']] = {
            'kind': kind,
            'targeting': 'singleEnemy' if needs_target else 'none',
            'cost': cost,
            'rarity': card.get('Rarity') or 'Common',
        }
    print('  元数据     %3d 张（要目标 %d、X 费 %d、不可打出 %d）' % (
        len(meta),
        sum(1 for row in meta.values() if row['targeting'] == 'singleEnemy'),
        sum(1 for row in meta.values() if row['cost'] == 'X'),
        sum(1 for row in meta.values() if row['cost'] == '-')))

    write_module(
        META_OUT,
        [
            '// 生成物：`python native/build_zh_i18n.py` 重建，**不要手改**。',
            '//',
            '// 「种类」「要不要玩家选目标」「费用」「稀有度」都来自内容包',
            '// （`Cards[].Tags` + `Costs[]` + `Rarity` + 程序里的 `sel.eventTarget`）。',
            '// ⚠️ **不从动作表的 targetSlot 反推**：内核故意为"每张可出的牌 × 每个活敌人"各发一条',
            '// 动作（它无法廉价判断定向性），那是**枚举策略**，不是卡牌语义（第十四轮 Review P1-A）。',
            '',
            'export interface CardMeta {',
            '  readonly kind: "attack" | "skill" | "power" | "status" | "curse";',
            '  readonly targeting: "none" | "singleEnemy";',
            '  /** 能量费；`"X"` = X 费牌，`"-"` = 不可打出（诅咒/状态）。 */',
            '  readonly cost: number | "X" | "-";',
            '  /** 内容包的 `Rarity`（`Common` / `Uncommon` / `Rare` / …）。 */',
            '  readonly rarity: string;',
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
