"""i18n 扩展：事件表（id → 中文名/正文/选项）+ 选项标签 en→zh。

## 来源与判据

* **名字/正文**：`spire-archive.com/api/sts1/events`（lang=zh/en，13 种语言的官方数据）。
  内容的 `EventNodes` 里**没有**事件名（只有英文正文 `TextKey`），所以名字只能来自 API。
* **id 对照**：我们内容的事件 id 与 API 的 id 不是同一套命名（`scrap_pile` ↔ `SCRAP_OOZE`、
  `ancient_writing` ↔ `BACK_TO_BASICS`…），所以有一张**显式别名表** `EVENT_ALIASES`。
  别名是**逐条核对过英文正文**的（脚本用正文词重叠找候选，再人工确认），
  少数只能按语义判断的标 `[推断]`。
* **选项标签**：内容的 `Options[].Label` 是英文短句（`Take it` / `[Reach Inside]`），
  API 的 `choices[].option` 是官方中文。两张表**顺序与措辞都不完全一致**，所以
  `EVENT_LABELS` 是**人工确认过的** en→zh 表：能从 API 对上的用 API 的译法，
  对不上的手译并标 `[推断]`。
* **子节点正文**（`golden_idol.boulder` 这类）：API 只给根事件的一段描述，子节点正文
  **没有**官方中文来源 ⇒ 运行时回退到英文，并计入 `coverage()` 的回退数（可度量，不静默）。

## 用法

`python native/build_zh_i18n.py` 会把它拼进 `web-next/src/i18n/zh.ts` 的 `events` /
`eventLabels` 两个键。缓存已在 `native/zh_source/events.{zh,en}.json`。
"""

import io
import json
import os

NL = chr(10)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'native', 'zh_source')
CONTENT = os.path.join(ROOT, 'tools', 'contentc', 'packages', 'sts', 'sts.roguedeck.json')

# ── id 对照：我们的内容 id → API id ──────────────────────────────────────────
#
# 判据：脚本按**英文正文的词重叠**给候选（`native/` 里那次一次性扫描），再逐条人工确认。
# `[推断]` = 正文重叠弱、按语义判断的（`old_shrine`/`ancient_forge`/`purification_shrine`/
# `council_of_ghosts`/`the_ssssserpent`）。
EVENT_ALIASES = {
    'ancient_forge': 'ACCURSED_BLACKSMITH',   # [推断] 唯一的"熔炉"事件
    'ancient_writing': 'BACK_TO_BASICS',      # 古老文字
    'augmenter': 'DRUG_DEALER',               # 增益研究者
    'big_fish': 'BIG_FISH',
    'council_of_ghosts': 'GHOSTS',            # [推断] 幽灵议会
    'dead_adventurer': 'DEAD_ADVENTURER',
    'falling': 'FALLING',
    'forgotten_altar': 'FORGOTTEN_ALTAR',
    'golden_idol': 'GOLDEN_IDOL',
    'living_wall': 'LIVING_WALL',
    'masked_bandits': 'MASKED_BANDITS',
    'mind_bloom': 'MINDBLOOM',
    'mushrooms': 'MUSHROOMS',
    'mysterious_sphere': 'MYSTERIOUS_SPHERE',
    'nloth': 'N_LOTH',
    'old_beggar': 'BEGGAR',
    'old_shrine': 'GOLDEN_SHRINE',            # [推断] 金色神龛
    'pleading_vagrant': 'ADDICT',
    'purification_shrine': 'FOUNTAIN_OF_CLEANSING',  # [推断] 神圣泉水
    'scrap_pile': 'SCRAP_OOZE',
    'sensory_stone': 'SENSORYSTONE',
    'shining_light': 'SHINING_LIGHT',
    'the_cleric': 'THE_CLERIC',
    'the_colosseum': 'COLOSSEUM',
    'the_joust': 'THE_JOUST',
    'the_library': 'THE_LIBRARY',
    'the_mausoleum': 'THE_MAUSOLEUM',
    'the_moai_head': 'THE_MOAI_HEAD',
    'the_nest': 'NEST',
    'the_ssssserpent': 'LIARS_GAME',          # [推断] 蛇～
    'tomb_of_lord_red_mask': 'TOMB_OF_LORD_RED_MASK',
    'vampires': 'VAMPIRES',
    'winding_halls': 'WINDING_HALLS',
    'wing_statue': 'GOLDEN_WING',
    'world_of_goop': 'WORLD_OF_GOOP',
}

# API 里没有的事件：手写名字（**唯一的例外**，其余一律来自 API）。
EVENT_NAME_OVERRIDES = {
    'wandering_merchant': '流浪商人',
}

# ── 选项标签 en → zh ────────────────────────────────────────────────────────
#
# `api` = 与 API 的官方中文选项对上的（词重叠 ≥ 2 且人工确认）；
# `推断` = 对不上的，按 StS 中文惯用译法手译。
EVENT_LABELS = {
    'Agree': ('同意', 'api'),
    'Banana (heal 1/3)': ('香蕉（回复 1/3 最大生命）', 'api'),
    'Box (random relic + Regret)': ('盒子（随机遗物 + 悔恨）', 'api'),
    'Change (transform a card)': ('改变（变形一张牌）', 'api'),
    'Continue': ('继续', '推断'),
    'Deeper': ('更深', '推断'),
    'Destroy': ('摧毁', 'api'),
    'Disagree': ('反对', 'api'),
    'Donut (max HP +5)': ('甜甜圈（最大生命 +5）', 'api'),
    'Eat (heal 25%, Parasite)': ('吃下（回复 25% 生命，寄生）', 'api'),
    'Fight': ('战斗', '推断'),
    'Forget (remove a card)': ('遗忘（移除一张牌）', 'api'),
    'Gather Gold': ('收集金币', 'api'),
    'Grow (upgrade a card)': ('成长（升级一张牌）', 'api'),
    'Heal (35 Gold)': ('治疗（35 金币）', 'api'),
    'Hide': ('躲起来', '推断'),
    'Leave': ('离开', 'api'),
    'Leave It': ('放手吧', 'api'),
    'Leave it': ('放手吧', 'api'),
    'Leave them be': ('别管它们', '推断'),
    'Outrun': ('逃跑', '推断'),
    'Pray': ('祈祷', 'api'),
    'Purify (50 Gold)': ('净化（50 金币）', 'api'),
    'Reach Inside': ('伸手进去', 'api'),
    'Search': ('搜索', 'api'),
    'Smash': ('砸碎', '推断'),
    'Step into it': ('走进去', '推断'),
    'Stomp (fight 3 Fungi Beasts)': ('踩扁（与 3 只真菌兽战斗）', 'api'),
    'Study the glyphs': ('研究符文', '推断'),
    'Take it': ('拿走', '推断'),
    'Take the Odd Mushroom': ('拿走奇怪的蘑菇', '推断'),
    'Walk on': ('继续前进', '推断'),
}


def build_events(content):
    """返回 `(events, labels, stats)`：事件表、标签表、统计（给控制台与闸门看）。"""
    zh_path = os.path.join(CACHE, 'events.zh.json')
    en_path = os.path.join(CACHE, 'events.en.json')
    if not (os.path.exists(zh_path) and os.path.exists(en_path)):
        raise SystemExit('缺事件缓存：先跑一次 `python native/build_zh_i18n.py --refresh`')
    zh = {item['id']: item for item in json.load(io.open(zh_path, encoding='utf-8'))['items']}
    en = {item['id']: item for item in json.load(io.open(en_path, encoding='utf-8'))['items']}

    nodes = content['EventNodes']
    roots = sorted({node['Id'].split('.')[0] for node in nodes})
    events = {}
    stats = {'roots': len(roots), 'named': 0, 'text': 0, 'options': 0, 'missing': [], 'optionMismatch': []}

    for event_id in roots:
        api_id = EVENT_ALIASES.get(event_id)
        entry = {'name': EVENT_NAME_OVERRIDES.get(event_id, ''), 'text': '', 'options': []}
        if api_id and api_id in zh:
            item = zh[api_id]
            entry['name'] = entry['name'] or item.get('name', '')
            entry['text'] = (item.get('description') or '').strip()
            # 根节点的选项：**只有条数一致**才按序号对（序号是唯一的对应关系，
            # 条数不一致说明两边的分支不同，硬对会张冠李戴）。
            root_node = next((node for node in nodes if node['Id'] == event_id), None)
            mine = [option.get('Label', '') for option in (root_node or {}).get('Options', [])]
            theirs = [choice.get('option', '') for choice in item.get('choices', [])]
            if mine and len(mine) == len(theirs):
                entry['options'] = theirs
                stats['options'] += len(theirs)
            elif mine:
                stats['optionMismatch'].append((event_id, len(mine), len(theirs)))
        if not entry['name']:
            stats['missing'].append(event_id)
        else:
            stats['named'] += 1
        if entry['text']:
            stats['text'] += 1
        events[event_id] = entry

    labels = {english: chinese for english, (chinese, _source) in EVENT_LABELS.items()}
    return events, labels, stats
