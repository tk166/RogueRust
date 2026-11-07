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
    # §242：`Whenever you play a Skill, {{KW|Exhaust}} **it**.` —— "it" 是那个技能，不是 Corruption
    # 自己（Power 打完进弃牌堆）。第四次遇到"Exhaust 有宾语"。
    'corruption': {
        'why': 'wiki 的 Exhaust 指的是**被打出的那个技能**（"Exhaust it"），Corruption 自己进弃牌堆。',
        'content_keywords': [],
    },
    # §241：`... and Exhaust **it**.` —— "it" 是被打出的**那张**牌，不是 Havoc 自己。
    # 与 `burning_pact` / `sever_soul` 同源：wiki 的 `{{KW|Exhaust}}` 在这里是动词。
    'havoc': {
        'why': 'wiki 的 Exhaust 指的是被打出的那张牌（"and Exhaust **it**"），Havoc 自己进弃牌堆。',
        'content_keywords': [],
    },
    # §239：与 `sever_soul` 同源 —— wiki 的 `{{KW|Exhaust}} 1 card.` 里那个 Exhaust 是**动词**
    # （"消耗一张牌"），不是这张牌自己的关键字：Burning Pact 打完进弃牌堆。
    'burning_pact': {
        'why': 'wiki 的 {{KW|Exhaust}} 是动词（消耗选中的一张牌），不是本牌的关键字；'
               '牌本身打完进弃牌堆。',
        'content_keywords': [],
    },
    # §236：Brutality 的 dump 是 `(;{{KW|Innate}}. <br>)At the start of your turn, lose 1 HP and
    # draw 1 card.` —— 括号里是"基础;升级"，**Innate 只属于升级版**。词条解析器只看
    # `{{KW|...}}` 出现与否，分不出"只属于升级"，所以这里显式声明基础版没有 Innate。
    'brutality': {
        'why': 'wiki 的 Innate 在 `(基础;升级)` 括号里 ⇒ 只有 brutality+ 是 Innate。',
        'content_keywords': [],
    },
    # §235：`Sever Soul` 的 dump 里 `{{KW|Exhaust}}` 是**动词**（"Exhaust all non-Attack cards in
    # your hand"），不是这张牌自己的关键字 —— 它自己不消耗。词条解析器只看 `{{KW|...}}` 标记，
    # 分不出"作为动词的 Exhaust"，所以这里显式声明：内容**没有** Exhaust 关键字。
    'sever_soul': {
        'why': 'wiki 的 {{KW|Exhaust}} 是动词（消耗手里的非攻击牌），不是本牌的关键字；'
               '牌本身打完进弃牌堆。',
        'content_keywords': [],
    },
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
    'anger': ([('damage', 6, 'event'), ('card', 'anger', 1, 'DiscardPile', 'source')],
              [('damage', 8, 'event'), ('card', 'anger+', 1, 'DiscardPile', 'source')]),
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
                       ('status', 'standard.no_draw', 1, 'source')],
                      [('draw', 4, 'source'),
                       ('status', 'standard.no_draw', 1, 'source')]),
    # §221：事件诅咒（没有数字，只有关键字；Doubt 的回合末效果在 `LifecyclePrograms` 里）。
    'doubt': ([], None),
    'writhe': ([], None),
    # ---- §225：整手牌逐张消耗（数字来自 native/wiki_cards/*.txt） -----------------------------
    'second_wind': ([('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                       ('block', 5, 'source')))],
                    [('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                       ('block', 7, 'source')))]),
    'fiend_fire': ([('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),
                                      ('damage', 7, 'event')))],
                   [('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),
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
    # §228：`Deal 3 damage to a random enemy (3;4) times.` —— 升级改次数。
    'sword_boomerang': ([('damageRandom', 3, 'allEnemies', 3)],
                        [('damageRandom', 3, 'allEnemies', 4)]),
    # §228：`Deal damage equal to your Block.` —— `+` 只降费。
    'body_slam': ([('damage', ('pool', 'standard.block', 'source'), 'event')],
                  [('damage', ('pool', 'standard.block', 'source'), 'event')]),
    # §229：`Deal (7;9) damage to a random enemy twice.` —— 升级改伤害，次数固定 2。
    'rip_and_tear': ([('damageRandom', 7, 'allEnemies', 2)],
                     [('damageRandom', 9, 'allEnemies', 2)]),
    # §229：`Deal 8 damage. Increase this card's damage by (5;8) this combat.`
    'rampage': ([('damage', ('add', 8, ('cardCounter', 'standard.rampage_bonus')), 'event'),
                 ('cardCounter', 'cardInstance.resolving', 'standard.rampage_bonus', 5, 'Add')],
                [('damage', ('add', 8, ('cardCounter', 'standard.rampage_bonus')), 'event'),
                 ('cardCounter', 'cardInstance.resolving', 'standard.rampage_bonus', 8, 'Add')]),
    # §229：`Deal (12;16) damage. Can be Upgraded any number of times.` —— 每档 +4，`plus` 是**第一档**。
    'searing_blow': ([('damage', 12, 'event')], [('damage', 16, 'event')]),
    # §230：`Gain (2;4) Strength. At the end of this turn, lose (2;4) Strength.`
    'flex': ([('status', 'standard.strength', 2, 'source'),
              ('status', 'standard.lose_strength', 2, 'source')],
             [('status', 'standard.strength', 4, 'source'),
              ('status', 'standard.lose_strength', 4, 'source')]),
    # §230：`Double your Strength.`（基础版 Exhaust，`+` 不消耗 —— 升级**去掉** Exhaust）
    'limit_break': ([('modify', 'standard.strength', ('expr', 'combatantStatusStacks'), 'source')],
                    [('modify', 'standard.strength', ('expr', 'combatantStatusStacks'), 'source')]),
    # §230：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing "Strike".`
    'perfected_strike': ([('damagePerTag', 6, 2, 'strike', 'event')],
                         [('damagePerTag', 6, 3, 'strike', 'event')]),
    # §231：`Gain (7;9) Block. Exhaust a random card in your hand.`
    'true_grit': ([('block', 7, 'source'),
                   ('select', 'source', 'Hand', None, 'Random', 1, 'ExhaustPile')],
                  [('block', 9, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'Exhaust')]),
    # §231：`Deal (4;5) damage to ALL enemies. Heal unblocked damage dealt.`
    'reaper': ([('damageHealLoss', 4, 'allEnemies')],
               [('damageHealLoss', 5, 'allEnemies')]),
    # §232：`Deal (7;10) damage X times.`（X 费）
    'skewer': ([('repeat', ('expr', 'x.cost'), 'damage', 7, 'event')],
               [('repeat', ('expr', 'x.cost'), 'damage', 10, 'event')]),
    # §232：`Enemy loses X Strength and gains X Weak. Exhaust.`（`+` 只降费 —— 两行事实相同）
    'malaise': ([('modify', 'standard.strength', ('expr', 'subtract'), 'event'),
                 ('status', 'standard.weak', ('expr', 'x.cost'), 'event')],
                [('modify', 'standard.strength', ('expr', 'subtract'), 'event'),
                 ('status', 'standard.weak', ('expr', 'add'), 'event')]),
    # §233：`Double your Block.`（`+` 只降费）—— `set` 语义，所以事实是 `setPool`。
    'entrench': ([('setPool', 'standard.block',
                   ('multiply', 2, ('pool', 'standard.block', 'source')), 'source')],
                 [('setPool', 'standard.block',
                   ('multiply', 2, ('pool', 'standard.block', 'source')), 'source')]),
    # ---- §235：35 张红卡的第一批（14 张） -----------------------------------------------
    'carnage': ([('damage', 20, 'event')], [('damage', 28, 'event')]),
    'demon_form': ([('status', 'standard.demon_form', 2, 'source')], [('status', 'standard.demon_form', 3, 'source')]),
    'disarm': ([('modify', 'standard.strength', -2, 'event')], [('modify', 'standard.strength', -3, 'event')]),
    'dropkick': ([('damage', 5, 'event'), ('when', None, 'gain', 'standard.energy', 1, 'source'), ('when', None, 'draw', 1, 'source')], [('damage', 8, 'event'), ('when', None, 'gain', 'standard.energy', 1, 'source'), ('when', None, 'draw', 1, 'source')]),
    'flame_barrier': ([('block', 12, 'source'), ('status', 'standard.flame_barrier', 4, 'source')], [('block', 16, 'source'), ('status', 'standard.flame_barrier', 6, 'source')]),
    'headbutt': ([('damage', 9, 'event'), ('choose', 'source', 'DiscardPile', (), 1, 1, 'ToDrawPileTop')], [('damage', 12, 'event'), ('choose', 'source', 'DiscardPile', (), 1, 1, 'ToDrawPileTop')]),
    'immolate': ([('damage', 21, 'allEnemies'), ('card', 'burn', 1, 'DiscardPile', 'source')], [('damage', 28, 'allEnemies'), ('card', 'burn', 1, 'DiscardPile', 'source')]),
    'intimidate': ([('status', 'standard.weak', 1, 'allEnemies')], [('status', 'standard.weak', 2, 'allEnemies')]),
    'power_through': ([('card', 'wound', 2, 'Hand', 'source'), ('block', 15, 'source')], [('card', 'wound', 2, 'Hand', 'source'), ('block', 20, 'source')]),
    'rage': ([('status', 'standard.rage', 3, 'source')], [('status', 'standard.rage', 5, 'source')]),
    'reckless_charge': ([('damage', 7, 'event'), ('card', 'dazed', 1, 'DrawPile', 'source')], [('damage', 10, 'event'), ('card', 'dazed', 1, 'DrawPile', 'source')]),
    'seeing_red': ([('gain', 'standard.energy', 2, 'source')], [('gain', 'standard.energy', 2, 'source')]),
    'sever_soul': ([('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),))], [('each', 'Hand', 'PileOrder', None, (('move', 'cardInstance.iterated', 'ExhaustPile'),))]),
    'shockwave': ([('status', 'standard.weak', 3, 'allEnemies'), ('status', 'standard.vulnerable', 3, 'allEnemies')], [('status', 'standard.weak', 5, 'allEnemies'), ('status', 'standard.vulnerable', 5, 'allEnemies')]),
    # ---- §236：失去生命（5 张） -----------------------------------------------------------
    'bloodletting': ([('loseHp', 3, 'source'), ('gain', 'standard.energy', 2, 'source')], [('loseHp', 3, 'source'), ('gain', 'standard.energy', 3, 'source')]),
    'brutality': ([('status', 'standard.brutality', 1, 'source')], [('status', 'standard.brutality', 1, 'source')]),
    'hemokinesis': ([('loseHp', 2, 'source'), ('damage', 15, 'event')], [('loseHp', 2, 'source'), ('damage', 20, 'event')]),
    'offering': ([('loseHp', 6, 'source'), ('gain', 'standard.energy', 2, 'source'), ('draw', 3, 'source')], [('loseHp', 6, 'source'), ('gain', 'standard.energy', 2, 'source'), ('draw', 5, 'source')]),
    'rupture': ([('status', 'standard.rupture', 1, 'source')], [('status', 'standard.rupture', 2, 'source')]),
    # ---- §237：触发器钩子（5 张 Power） -------------------------------------------------
    'dark_embrace': ([('status', 'standard.dark_embrace', 1, 'source')], [('status', 'standard.dark_embrace', 1, 'source')]),
    'evolve': ([('status', 'standard.evolve', 1, 'source')], [('status', 'standard.evolve', 2, 'source')]),
    'feel_no_pain': ([('status', 'standard.feel_no_pain', 3, 'source')], [('status', 'standard.feel_no_pain', 4, 'source')]),
    'fire_breathing': ([('status', 'standard.fire_breathing', 6, 'source')], [('status', 'standard.fire_breathing', 10, 'source')]),
    'juggernaut': ([('status', 'standard.juggernaut', 5, 'source')], [('status', 'standard.juggernaut', 7, 'source')]),
    # ---- §238：余额基建的第一批（4 张） -------------------------------------------------
    'double_tap': ([('status', 'standard.double_tap', 1, 'source')], [('status', 'standard.double_tap', 2, 'source')]),
    'exhume': ([('choose', 'source', 'ExhaustPile', (), 1, 1, 'ToHand')], [('choose', 'source', 'ExhaustPile', (), 1, 1, 'ToHand')]),
    'feed': ([('damage', 10, 'event'), ('ifFatalGainMaxHealth', 3)], [('damage', 12, 'event'), ('ifFatalGainMaxHealth', 4)]),
    'heavy_blade': ([('damage', ('expr', 'add'), 'event')], [('damage', ('expr', 'add'), 'event')]),
    # ---- §239：PlayCondition 的第一张（1 张） -------------------------------------------
    'clash': ([('damage', 14, 'event')], [('damage', 18, 'event')]),
    'burning_pact': ([('choose', 'source', 'Hand', (), 1, 1, 'Exhaust'), ('draw', 2, 'source')], [('choose', 'source', 'Hand', (), 1, 1, 'Exhaust'), ('draw', 3, 'source')]),
    'infernal_blade': ([('createRandom', 'attack', 'Hand', 1, True)], [('createRandom', 'attack', 'Hand', 1, True)]),
    'havoc': ([('playTopOfDrawPile', 'ExhaustPile')], [('playTopOfDrawPile', 'ExhaustPile')]),
    # ---- §242：最后三张红卡（3 张） -------------------------------------------------------
    'spot_weakness': ([('when', None, 'status', 'standard.strength', 3, 'source')], [('when', None, 'status', 'standard.strength', 4, 'source')]),
    'blood_for_blood': ([('damage', 18, 'event')], [('damage', 22, 'event')]),
    'corruption': ([('status', 'standard.corruption', 1, 'source')], [('status', 'standard.corruption', 1, 'source')]),
    # ---- §243：无色 A 档（11 张）----------------------------------------------------------
    'trip': ([('status', 'standard.vulnerable', 2, 'event')], [('status', 'standard.vulnerable', 2, 'allEnemies')]),
    'panacea': ([('status', 'standard.artifact', 1, 'source')], [('status', 'standard.artifact', 2, 'source')]),
    'finesse': ([('block', 2, 'source'), ('draw', 1, 'source')], [('block', 4, 'source'), ('draw', 1, 'source')]),
    'flash_of_steel': ([('damage', 3, 'event'), ('draw', 1, 'source')], [('damage', 6, 'event'), ('draw', 1, 'source')]),
    'good_instincts': ([('block', 6, 'source')], [('block', 9, 'source')]),
    'master_of_strategy': ([('draw', 3, 'source')], [('draw', 4, 'source')]),
    'dramatic_entrance': ([('damage', 8, 'allEnemies')], [('damage', 12, 'allEnemies')]),
    'impatience': ([('when', None, 'draw', 2, 'source')], [('when', None, 'draw', 3, 'source')]),
    'deep_breath': ([('shuffleDiscard', 'source'), ('draw', 1, 'source')], [('shuffleDiscard', 'source'), ('draw', 2, 'source')]),
    'insight': ([('draw', 2, 'source')], [('draw', 3, 'source')]),
    'miracle': ([('gain', 'standard.energy', 1, 'source')], [('gain', 'standard.energy', 2, 'source')]),
    # ---- §244：无色 B 档（10 张）----------------------------------------------------------
    'mayhem': ([('status', 'standard.mayhem', 1, 'source')], [('status', 'standard.mayhem', 1, 'source')]),
    'magnetism': ([('status', 'standard.magnetism', 1, 'source')], [('status', 'standard.magnetism', 1, 'source')]),
    'chrysalis': ([('createRandom', 'skill', 'DrawPile', 3, True)], [('createRandom', 'skill', 'DrawPile', 5, True)]),
    'metamorphosis': ([('createRandom', 'attack', 'DrawPile', 3, True)], [('createRandom', 'attack', 'DrawPile', 5, True)]),
    'jack_of_all_trades': ([('createRandom', 'colorless', 'Hand', 1, True)], [('createRandom', 'colorless', 'Hand', 2, True)]),
    'transmutation': ([('createRandom', 'colorless', 'Hand', ('expr', 'x.cost'), True)], [('createRandom', 'colorless', 'Hand', ('expr', 'x.cost'), True)]),
    'secret_technique': ([('choose', 'source', 'DrawPile', ('skill',), 1, 1, 'ToHand')], [('choose', 'source', 'DrawPile', ('skill',), 1, 1, 'ToHand')]),
    'secret_weapon': ([('choose', 'source', 'DrawPile', ('attack',), 1, 1, 'ToHand')], [('choose', 'source', 'DrawPile', ('attack',), 1, 1, 'ToHand')]),
    'violence': ([('select', 'source', 'DrawPile', None, 'Random', 3, 'Hand')], [('select', 'source', 'DrawPile', None, 'Random', 4, 'Hand')]),
    'purity': ([('choose', 'source', 'Hand', (), 1, 3, 'Exhaust')], [('choose', 'source', 'Hand', (), 1, 5, 'Exhaust')]),
    # ---- §245：无色「既有载体」第一批（3 张）----------------------------------------------
    'apotheosis': ([('upgrade', 'source', None, None, None)], [('upgrade', 'source', None, None, None)]),
    'panic_button': ([('block', 30, 'source'), ('status', 'standard.no_block_from_cards', 1, 'source')], [('block', 40, 'source'), ('status', 'standard.no_block_from_cards', 1, 'source')]),
    'thinking_ahead': ([('draw', 2, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')], [('draw', 2, 'source'), ('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileTop')]),
    # ---- §247：Mind Blast / Enlightenment（2 张）------------------------------------------
    'mind_blast': ([('damage', ('expr', 'combatantZoneCount'), 'event')], [('damage', ('expr', 'combatantZoneCount'), 'event')]),
    # ---- §248：Enlightenment / Madness（2 张）----------------------------------------------
    'enlightenment': ([('status', 'standard.cap_cost_at', 1, 'source')], [('status', 'standard.cap_cost_at', 1, 'source')]),
    'madness': ([('each', 'Hand', 'Random', 1, (('cardCounter', 'cardInstance.iterated', 'standard.card_cost_override', 0, 'Set'),))], [('each', 'Hand', 'Random', 1, (('cardCounter', 'cardInstance.iterated', 'standard.card_cost_override', 0, 'Set'),))]),
    # ---- §249：Omega / Panache / Sadistic Nature / The Bomb（4 张）-------------------------
    'omega': ([('status', 'standard.omega', 50, 'source')], [('status', 'standard.omega', 60, 'source')]),
    'panache': ([('status', 'standard.panache', 10, 'source')], [('status', 'standard.panache', 14, 'source')]),
    'sadistic_nature': ([('status', 'standard.sadistic_nature', 5, 'source')], [('status', 'standard.sadistic_nature', 7, 'source')]),
    'the_bomb': ([('status', 'standard.the_bomb_damage', 40, 'source'), ('status', 'standard.the_bomb', 3, 'source')], [('status', 'standard.the_bomb_damage', 50, 'source'), ('status', 'standard.the_bomb', 3, 'source')]),
    # ---- §250：B/C/D/F 四组（14 张牌）----------------------------------------------------
    'ritual_dagger': ([('damage', ('add', 15, ('multiply', ('cardCounter', 'standard.ritual_dagger_bonus'), 3)), 'event'), ('fatal', 'cardCounter', 'cardInstance.resolving', 'standard.ritual_dagger_bonus', 3, 'Add')], [('damage', ('add', 15, ('multiply', ('cardCounter', 'standard.ritual_dagger_bonus'), 5)), 'event'), ('fatal', 'cardCounter', 'cardInstance.resolving', 'standard.ritual_dagger_bonus', 5, 'Add')]),
    'hand_of_greed': ([('damage', 20, 'event'), ('fatal', 'gold', 20)], [('damage', 25, 'event'), ('fatal', 'gold', 25)]),
    'forethought': ([('choose', 'source', 'Hand', (), 1, 1, 'ToDrawPileBottomFree')], [('choose', 'source', 'Hand', (), 0, 10, 'ToDrawPileBottomFree')]),
    'clumsy': ([], None),
    'curse_of_the_bell': ([], None),
    'decay': ([], None),
    'necronomicurse': ([], None),
    'normality': ([], None),
    'pain': ([], None),
    'parasite': ([], None),
    'pride': ([], None),
    'regret': ([], None),
    'shame': ([], None),
    # ---- §251：A 组 5 张 ------------------------------------------------------------------
    'bite': ([('damage', 7, 'event'), ('heal', 2, 'source')], [('damage', 8, 'event'), ('heal', 3, 'source')]),
    'expunger': ([('repeat', ('cardCounter', 'standard.expunger_x'), 'damage', 9, 'event')], [('repeat', ('cardCounter', 'standard.expunger_x'), 'damage', 15, 'event')]),
    'shiv': ([('damage', 4, 'event')], [('damage', 6, 'event')]),
    'smite': ([('damage', 12, 'event')], [('damage', 16, 'event')]),
    'beta': ([('card', 'omega', 1, 'DrawPile', 'source')], [('card', 'omega', 1, 'DrawPile', 'source')]),
    # 没有数字的牌：纯关键字/状态牌。
    'slimed': ([], None),
    'wound': ([], None),
    'burn': ([], []),
    'dazed': ([], None),
    'void': ([], None),
    'injury': ([], None),
    'ascenders_bane': ([], None),
}
