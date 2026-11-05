"""§218: `INV_CARD_WIKI` — the wiki's own answer for every card in this content.

Structure per **base** id (the `+` row is compared against the `plus` entry, so one row covers both):

    (type, rarity, cost, keywords, base_facts, plus_facts, deviation)

* `type` / `rarity` / `cost` come straight from the infobox (`sts_content_check` reads the dump at
  check time through `native/wiki_cards.py`, so those three cannot drift away from the page);
  this table only carries the **numbers** and the declarations.
* `base_facts` / `plus_facts` use the same vocabulary as `INV_CARDS` facts
  (`("damage", 6, "event")`, `("block", 5, "source")`, `("status", "standard.weak", 2, "allEnemies")`).
  `plus_facts = None` means "this content has no upgraded row" -- which is itself a finding.
* `deviation` 非空 = **内容与 wiki 已知不同**，写清原因；检查函数会要求内容等于 `deviation` 描述的那个
  形状（`content_facts` / `content_keywords` / `content_rarity` / `content_cost_tag`），而不是 wiki 的。

为什么要这张表（而不是解析 wiki 的散文）：Descrption 是给玩家读的句子
（`Deal (8;10) damage.<br>Apply (2;3) {{BD|Vulnerable}}.`），把它解析成事实等于在闸门里再实现一遍规则。
字段（类型/稀有度/费用/关键字）是机器可读的，所以那四项**不抄**，直接从 dump 读。
"""
import io

# §218 的偏差声明（内容 vs wiki）。key = 基础 id；值里的字段只写**与 wiki 不同**的那几项。
DEVIATIONS = {
    # §219：slimed 的偏差已经**修掉**了（现在可出、落区 ExhaustPile）—— 载体早就存在，
    # 只是 §218 把 wiki 的 `Exhaust` 当成了 tag。这里不再声明。
    'sentinel': {
        'why': 'wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"'
               '**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。',
        'content_keywords': ['Ethereal'],
    },
    'void': {
        'why': 'wiki: 抽到时失去 1 点能量。内容缺这条触发器（`OnDrawn` 对牌还没有载体），'
               '所以 Void 目前只是"不可出的虚无牌"。',
        'content_keywords': ['Ethereal', 'Unplayable'],
    },
    'burn': {
        'why': 'wiki 升级版是"回合末受 4 点伤害"，内容只有基础版（`burn+` 那一行没有生命周期）。',
        'plus_facts': [],
    },
    'bandage_up': {
        'why': 'wiki 升级版治疗 6；内容没有 `bandage_up+` 这一行。'
               '（`Exhaust` 本身不是偏差：§219 起它由落区 `PlayedCardDestinationZone` 表达。）',
        'plus_facts': None,
    },
    'dark_shackles': {
        'why': 'wiki 升级版是 15 层；内容没有 `dark_shackles+` 这一行。'
               '（`Exhaust` 同 `bandage_up`：由落区表达，不是偏差。）',
        'plus_facts': None,
    },
}

# (base_facts, plus_facts) —— 数字全部抄自 `native/wiki_cards/<id>.txt` 的 Description：
#   `(a;b)` = 基础;升级。`None` = 这一侧没有数字（纯关键字牌）。
FACTS = {
    'strike': ([('damage', 6, 'event')], [('damage', 9, 'event')]),
    'defend': ([('block', 5, 'source')], [('block', 8, 'source')]),
    'bash': ([('damage', 8, 'event'), ('status', 'standard.vulnerable', 2, 'event')],
             [('damage', 10, 'event'), ('status', 'standard.vulnerable', 3, 'event')]),
    'twin_strike': ([('damage', 5, 'event'), ('damage', 5, 'event')],
                    [('damage', 7, 'event'), ('damage', 7, 'event')]),
    'iron_wave': ([('block', 5, 'source'), ('damage', 5, 'event')],
                  [('block', 7, 'source'), ('damage', 7, 'event')]),
    'clothesline': ([('damage', 12, 'event'), ('status', 'standard.weak', 2, 'event')],
                    [('damage', 14, 'event'), ('status', 'standard.weak', 3, 'event')]),
    'anger': ([('damage', 6, 'event'), ('card', 'anger', 1, 'DiscardPile', 'event')],
              [('damage', 8, 'event'), ('card', 'anger+', 1, 'DiscardPile', 'event')]),
    'uppercut': ([('damage', 13, 'event'), ('status', 'standard.weak', 1, 'event'),
                  ('status', 'standard.vulnerable', 1, 'event')],
                 [('damage', 13, 'event'), ('status', 'standard.weak', 2, 'event'),
                  ('status', 'standard.vulnerable', 2, 'event')]),
    'whirlwind': ([('repeat', ('expr', 'x.cost'), 'damage', 5, 'allEnemies')],
                  [('repeat', ('expr', 'x.cost'), 'damage', 8, 'allEnemies')]),
    'bandage_up': ([('heal', 4, 'sourceDowned')], [('heal', 6, 'sourceDowned')]),
    'blind': ([('status', 'standard.weak', 2, 'allEnemies')], None),
    # "Enemy loses 9 (15) Strength **this turn**" = 立刻降 + 回合末还（§219）。
    # 原来写的是 `applyStatus(strength, -9)`，而负层数会被内核拒绝 ⇒ 这张牌打出即 fault。
    'dark_shackles': ([('modify', 'standard.strength', -9, 'event'),
                       ('status', 'standard.regain_strength', 9, 'event')],
                      [('modify', 'standard.strength', -15, 'event'),
                       ('status', 'standard.regain_strength', 15, 'event')]),
    'inflame': ([('status', 'standard.strength', 2, 'source')],
                [('status', 'standard.strength', 3, 'source')]),
    'metallicize': ([('status', 'standard.metallicize', 3, 'source')],
                    [('status', 'standard.metallicize', 4, 'source')]),
    'combust': ([('status', 'standard.combust', 5, 'source')],
                [('status', 'standard.combust', 7, 'source')]),
    'barricade': ([('status', 'standard.barricade', 1, 'source')],
                  [('status', 'standard.barricade', 1, 'source')]),
    'blur': ([('block', 5, 'source'), ('status', 'standard.blur', 1, 'source')],
             [('block', 8, 'source'), ('status', 'standard.blur', 1, 'source')]),
    'buffer': ([('status', 'standard.buffer', 1, 'source')],
               [('status', 'standard.buffer', 2, 'source')]),
    'berserk': ([('status', 'standard.vulnerable', 2, 'source'),
                 ('status', 'standard.berserk', 1, 'source')],
                [('status', 'standard.vulnerable', 1, 'source'),
                 ('status', 'standard.berserk', 1, 'source')]),
    # §223：wiki —— 升级只去掉 Ethereal，两层都 1 层无形。
    'apparition': ([('status', 'standard.intangible', 1, 'source')],
                   [('status', 'standard.intangible', 1, 'source')]),
    'sentinel': ([('block', 5, 'source')], [('block', 8, 'source')]),
    # ---- §221: the ten new cards, transcribed from `native/wiki_cards/*.txt` -------------------
    'cleave': ([('damage', 8, 'allEnemies')], [('damage', 11, 'allEnemies')]),
    'pommel_strike': ([('damage', 9, 'event'), ('draw', 1, 'source')],
                      [('damage', 10, 'event'), ('draw', 2, 'source')]),
    'shrug_it_off': ([('block', 8, 'source'), ('draw', 1, 'source')],
                     [('block', 11, 'source'), ('draw', 1, 'source')]),
    'thunderclap': ([('damage', 4, 'allEnemies'),
                     ('status', 'standard.vulnerable', 1, 'allEnemies')],
                    [('damage', 7, 'allEnemies'),
                     ('status', 'standard.vulnerable', 1, 'allEnemies')]),
    'bludgeon': ([('damage', 32, 'event')], [('damage', 42, 'event')]),
    'impervious': ([('block', 30, 'source')], [('block', 40, 'source')]),
    'pummel': ([('repeat', 4, 'damage', 2, 'event')], [('repeat', 5, 'damage', 2, 'event')]),
    'wild_strike': ([('damage', 12, 'event'), ('card', 'wound', 1, 'DrawPile', 'source')],
                    [('damage', 17, 'event'), ('card', 'wound', 1, 'DrawPile', 'source')]),
    'ghostly_armor': ([('block', 10, 'source')], [('block', 13, 'source')]),
    'battle_trance': ([('draw', 3, 'source'),
                       ('status', 'standard.draw_reduction', 1, 'source')],
                      [('draw', 4, 'source'),
                       ('status', 'standard.draw_reduction', 1, 'source')]),
    # §221：事件诅咒（没有数字，只有关键字；Doubt 的回合末效果在 `LifecyclePrograms` 里）。
    'doubt': ([], None),
    'writhe': ([], None),
    # ---- §225：整手牌逐张消耗（数字来自 native/wiki_cards/*.txt） -----------------------------
    'second_wind': ([('each', 'Hand', (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                       ('block', 5, 'source')))],
                    [('each', 'Hand', (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                       ('block', 7, 'source')))]),
    'fiend_fire': ([('each', 'Hand', (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                      ('damage', 7, 'event')))],
                   [('each', 'Hand', (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                      ('damage', 10, 'event')))]),
    # §226：`Dual Wield` —— wiki 的 "Add (a copy;2 copies) of that card into your hand."
    # 两行只差 `Copies`（1 / 2），这正是升级的全部内容。
    # §227：事实里多了 `Then`（以及 `Copy` 的落区与份数），因为同一个节点现在能表达三种"选完做什么"。
    'dual_wield': ([('choose', 'source', 'Hand', ('attack', 'power'), 1, 1, 'Copy', 'Hand', 1)],
                   [('choose', 'source', 'Hand', ('attack', 'power'), 1, 1, 'Copy', 'Hand', 2)]),
    # wiki：`Gain 5 Block. Upgrade (a card;all cards) in your hand for the rest of combat.`
    'armaments': ([('block', 5, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'Upgrade')],
                  [('block', 5, 'source'), ('upgrade', 'source', None, 'Hand', None)]),
    # wiki：`Draw (1;2) card(s). Put a card from your hand onto the top of your draw pile. Exhaust.`
    'warcry': ([('draw', 1, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')],
               [('draw', 2, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')]),
    # wiki：`Choose a card. Next turn, add 3 copies of that card into your hand. Exhaust.`（`+` 只降费）
    'nightmare': ([('choose', 'source', 'Hand', (), 1, 1, 'Copy', 'SetAsidePile', 3),
                   ('status', 'standard.nightmare_pending', 1, 'source')],
                  [('choose', 'source', 'Hand', (), 1, 1, 'Copy', 'SetAsidePile', 3),
                   ('status', 'standard.nightmare_pending', 1, 'source')]),
    # 没有数字的牌：纯关键字/状态牌。
    'slimed': ([], None),
    'wound': ([], None),
    'burn': ([], []),
    'dazed': ([], None),
    'void': ([], None),
    'injury': ([], None),
    'ascenders_bane': ([], None),
}
