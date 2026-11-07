"""§218: read `native/wiki_cards/<id>.txt` (raw wikitext, one per card).

Why a parser and not a hand table for the *fields*: `Type` / `Rarity` / `Cost` / the `{{KW|...}}`
keyword markers are unambiguous, so reading them at check time means the expectation cannot drift away
from the dump. The **numbers** are not parsed here -- the wiki writes them in prose
(`Deal (8;10) damage.<br>Apply (2;3) {{BD|Vulnerable}}.`), and a prose parser in the gate would be a
second implementation of the rules. They live in `sts_content_check.INV_CARD_WIKI` instead, one row per
card, transcribed from these files and reviewed by eye (the dumps stay in the repo so that review can be
repeated).

`(8;10)` = base;upgraded. `Cost`: `-1` = X cost, `-2` = unplayable (the wiki's own encoding).
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, 'wiki_cards')

KEYWORDS = ('Unplayable', 'Ethereal', 'Exhaust', 'Innate', 'Retain')
TYPES = {'Attack': 'attack', 'Skill': 'skill', 'Power': 'power', 'Status': 'status',
         'Curse': 'curse'}


class WikiCardError(Exception):
    pass


def available():
    """本内容有、并且抓到了页面的卡牌 id（没有页面的不在这里）。"""
    if not os.path.isdir(DIR):
        return []
    return sorted(name[:-4] for name in os.listdir(DIR) if name.endswith('.txt'))


def parse(card_id):
    """→ {'name', 'type', 'rarity', 'cost', 'keywords', 'description'}。

    只认 `{{Card Infobox` 里的字段；`Cost` 保留 wiki 的编码（-1 = X，-2 = 不可出）。
    """
    path = os.path.join(DIR, card_id + '.txt')
    if not os.path.isfile(path):
        # §252：`j.a.x.` 的 dump 落在 `j_a_x.txt` —— 文件名里的点会被当成扩展名，
        # 所以抓取时把点换成了下划线。这里**只做路径别名**，卡 id 本身仍是 `j.a.x.`。
        # 尾点也要去掉：`j.a.x.` → `j_a_x`（不是 `j_a_x_`）。
        alias = os.path.join(DIR, card_id.replace('.', '_').rstrip('_') + '.txt')
        if os.path.isfile(alias):
            path = alias
        else:
            raise WikiCardError('%s: no dump under native/wiki_cards/ (fetch it first)' % card_id)
    text = io.open(path, encoding='utf-8').read()
    if '{{Card Infobox' not in text:
        raise WikiCardError('%s: the dump has no `{{Card Infobox` -- wrong page?' % card_id)
    box = text.split('{{Card Infobox', 1)[1]

    def field(name):
        match = re.search(r'\|\s*' + name + r'\s*=\s*([^\n]*)', box)
        return match.group(1).strip() if match else ''

    card_type = field('Type')
    if card_type not in TYPES:
        raise WikiCardError('%s: unknown Type %r' % (card_id, card_type))
    description = field('Description')
    cost_text = field('Cost')
    # §244：数据模块的两种非数字费用 —— `X`（X 费，`Cost = -1`）与 `Unplayable`（`-2`）。
    # 这里照抄那两个约定，而不是"解析失败就跳过"：跳过会让一张 X 费牌的费用**没人核对**。
    if cost_text == 'X':
        cost = -1
    elif cost_text in ('Unplayable', '-', '', '?'):
        # §252：`?` 是第三种写法 —— wiki 用它标"这张牌没有可打出的费用"（`Wish` 的三个选项：
        # `become_almighty` / `live_forever` / `fame_and_fortune` 的 Infobox 里就是 `Cost = ?`）。
        # 它与 `Unplayable` **同义**（玩家在手上打不出），所以落同一个 `-2`；不新增一个码位，
        # 因为下游（`sts_content_check`）只区分"数字 / X / 不可打出"这三类。
        cost = -2
    else:
        try:
            cost = int(cost_text)
        except ValueError:
            raise WikiCardError('%s: Cost is not an integer (%r)' % (card_id, cost_text))

    # `{{KW|Exhaust}}` 是关键字；`{{KW|Exhaust|Exhausted}}` 是**条件**（Sentinel 的
    # "if this card is Exhausted"），不是这张牌自带 Exhaust —— 有竖线的都不算关键字。
    keywords = sorted({match.group(1) for match in re.finditer(r'\{\{KW\|([A-Za-z ]+)\}\}', description)
                       if match.group(1) in KEYWORDS})
    return {
        'name': field('Name'),
        'type': TYPES[card_type],
        'rarity': field('Rarity') or None,
        'cost': cost,
        'keywords': keywords,
        'description': description,
    }
