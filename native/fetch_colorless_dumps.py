"""§243：把无色卡（含诅咒）的 wiki 原文落成 dump。

来源（**两次搜索拿全，不是逐页抓**）：
* `slaythespire.wiki.gg/wiki/Module:Cards/data` —— 40 张无色牌的
  `Cost / CostPlus / Color / Type / Rarity / Text`（本文件 `DATA` 逐字转写）；
* 同一模块的诅咒段（第一次搜索的 snippet 在表头之前被截断）+ `slayspiredb.com/sts1/curses-and-statuses`
  双源核对 10 张诅咒。

**转写约定**（与仓库既有 dump 一致，`card_wiki_inventory.py` 才解析得动）：
* 模块里的 `[a|b]`（基础|升级）→ `(a;b)`；
* `$Keyword` / `#Keyword` → `{{KW|Keyword}}`（**检查器靠这个判"wiki 有 Exhaust/Innate"**）；
* `Cost = -1` → `X`；`Cost = -2` → `Unplayable`；
* `@PE` / `<R>` → `Gain 1 Energy`（能量图标）。

⚠️ 标了 `UNVERIFIED` 的条目 = 原文没取到（`become_almighty`）或只拿到片段
（`fame_and_fortune` 的费用）。**这些在实现前必须先补原文**，别按记忆写内容。
"""
import io
import os

OUT = 'D:/Vibe/sts-tui/native/wiki_cards/'

# (id, Name, Color, Type, Rarity, Cost, CostPlus, Description)
DATA = [
    # ---- Uncommon Skill ----------------------------------------------------------------
    ('deep_breath', 'Deep Breath', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Shuffle your discard pile into your draw pile.<br>Draw (1 card;2 cards).'),
    ('discovery', 'Discovery', 'Colorless', 'Skill', 'Uncommon', '1', None,
     'Choose 1 of 3 random cards to add into your hand. It costs 0 this turn.'
     '<br>{{KW|Exhaust}}. (Upgraded: no {{KW|Exhaust}}.)'),
    ('enlightenment', 'Enlightenment', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Reduce the cost of all cards in your hand to 1 this (turn;combat).'),
    ('finesse', 'Finesse', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Gain (2;4) {{KW|Block}}.<br>Draw 1 card.'),
    ('forethought', 'Forethought', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Put (a card;any number of cards) from your hand to the bottom of your draw pile. '
     '(It costs;They cost) 0 until played.'),
    ('good_instincts', 'Good Instincts', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Gain (6;9) {{KW|Block}}.'),
    ('impatience', 'Impatience', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'If you have no Attacks in your hand, draw (2;3) cards.'),
    ('jack_of_all_trades', 'Jack of All Trades', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Add (1;2) random Colorless (card;cards) into your hand.<br>{{KW|Exhaust}}.'),
    ('madness', 'Madness', 'Colorless', 'Skill', 'Uncommon', '1', '0',
     'Reduce the cost of a random card in your hand to 0 this combat.<br>{{KW|Exhaust}}.'),
    ('panacea', 'Panacea', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Gain (1;2) {{KW|Artifact}}.<br>{{KW|Exhaust}}.'),
    ('panic_button', 'Panic Button', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Gain (30;40) {{KW|Block}}. You cannot gain {{KW|Block}} from cards for 2 turns.'
     '<br>{{KW|Exhaust}}.'),
    ('purity', 'Purity', 'Colorless', 'Skill', 'Uncommon', '0', None,
     '{{KW|Exhaust}} up to (3;5) cards in your hand.<br>{{KW|Exhaust}}.'),
    ('trip', 'Trip', 'Colorless', 'Skill', 'Uncommon', '0', None,
     'Apply 2 {{KW|Vulnerable}} to the target. (Upgraded: to ALL enemies.)'),
    # ---- Uncommon Attack ---------------------------------------------------------------
    ('dramatic_entrance', 'Dramatic Entrance', 'Colorless', 'Attack', 'Uncommon', '0', None,
     '{{KW|Innate}}.<br>Deal (8;12) damage to ALL enemies.<br>{{KW|Exhaust}}.'),
    ('flash_of_steel', 'Flash of Steel', 'Colorless', 'Attack', 'Uncommon', '0', None,
     'Deal (3;6) damage.<br>Draw 1 card.'),
    ('mind_blast', 'Mind Blast', 'Colorless', 'Attack', 'Uncommon', '2', '1',
     '{{KW|Innate}}.<br>Deal damage equal to the number of cards in your draw pile.'),
    # ---- Rare Skill --------------------------------------------------------------------
    ('apotheosis', 'Apotheosis', 'Colorless', 'Skill', 'Rare', '2', '1',
     '{{KW|Upgrade}} ALL your cards for the rest of combat.<br>{{KW|Exhaust}}.'),
    ('chrysalis', 'Chrysalis', 'Colorless', 'Skill', 'Rare', '2', None,
     'Shuffle (3;5) random Skills into your draw pile. They cost 0 this combat.'
     '<br>{{KW|Exhaust}}.'),
    ('master_of_strategy', 'Master of Strategy', 'Colorless', 'Skill', 'Rare', '0', None,
     'Draw (3;4) cards.<br>{{KW|Exhaust}}.'),
    ('metamorphosis', 'Metamorphosis', 'Colorless', 'Skill', 'Rare', '2', None,
     'Shuffle (3;5) random Attacks into your draw pile. They cost 0 this combat.'
     '<br>{{KW|Exhaust}}.'),
    ('secret_technique', 'Secret Technique', 'Colorless', 'Skill', 'Rare', '0', None,
     'Put a Skill from your draw pile into your hand.<br>{{KW|Exhaust}}. '
     '(Upgraded: no {{KW|Exhaust}}.)'),
    ('secret_weapon', 'Secret Weapon', 'Colorless', 'Skill', 'Rare', '0', None,
     'Put an Attack from your draw pile into your hand.<br>{{KW|Exhaust}}. '
     '(Upgraded: no {{KW|Exhaust}}.)'),
    ('the_bomb', 'The Bomb', 'Colorless', 'Skill', 'Rare', '2', None,
     'At the end of 3 turns, deal (40;50) damage to ALL enemies.'),
    ('thinking_ahead', 'Thinking Ahead', 'Colorless', 'Skill', 'Rare', '0', None,
     'Draw 2 cards.<br>Put a card from your hand on top of your draw pile.'
     '<br>{{KW|Exhaust}}. (Upgraded: no {{KW|Exhaust}}.)'),
    ('transmutation', 'Transmutation', 'Colorless', 'Skill', 'Rare', 'X', None,
     'Add X random Colorless cards into your hand. They cost 0 this turn. '
     '(Upgraded: the cards are {{KW|Upgrade}}d.)<br>{{KW|Exhaust}}.'),
    ('violence', 'Violence', 'Colorless', 'Skill', 'Rare', '0', None,
     'Put (3;4) random Attacks from your draw pile into your hand.<br>{{KW|Exhaust}}.'),
    # ---- Rare Attack -------------------------------------------------------------------
    ('hand_of_greed', 'Hand of Greed', 'Colorless', 'Attack', 'Rare', '2', None,
     'Deal (20;25) damage.<br>If {{KW|Fatal}}, gain (20;25) Gold.'),
    # ---- Rare Power --------------------------------------------------------------------
    ('magnetism', 'Magnetism', 'Colorless', 'Power', 'Rare', '2', '1',
     'At the start of your turn, add a random Colorless card into your hand.'),
    ('mayhem', 'Mayhem', 'Colorless', 'Power', 'Rare', '2', '1',
     'At the start of your turn, play the top card of your draw pile.'),
    ('panache', 'Panache', 'Colorless', 'Power', 'Rare', '0', None,
     'Every time you play 5 cards in a single turn, deal (10;14) damage to ALL enemies.'),
    ('sadistic_nature', 'Sadistic Nature', 'Colorless', 'Power', 'Rare', '0', None,
     'Whenever you apply a debuff to an enemy, they take (5;7) damage.'),
    # ---- Special Skill -----------------------------------------------------------------
    ('beta', 'Beta', 'Colorless', 'Skill', 'Special', '2', '1',
     'Shuffle an Omega into your draw pile.<br>{{KW|Exhaust}}.'),
    ('fame_and_fortune', 'Fame and Fortune', 'Colorless', 'Skill', 'Special', '?', None,
     'Gain (25;30) Gold.<br>UNVERIFIED: the cost was not in the fetched excerpt.'),
    ('insight', 'Insight', 'Colorless', 'Skill', 'Special', '0', None,
     '{{KW|Retain}}.<br>Draw (2;3) cards.<br>{{KW|Exhaust}}.'),
    ('j_a_x', "J.A.X.", 'Colorless', 'Skill', 'Special', '0', None,
     'Lose 3 HP.<br>Gain (2;3) {{KW|Strength}}.'),
    ('miracle', 'Miracle', 'Colorless', 'Skill', 'Special', '0', None,
     '{{KW|Retain}}.<br>Gain (1;2) Energy.<br>{{KW|Exhaust}}.'),
    ('safety', 'Safety', 'Colorless', 'Skill', 'Special', '1', None,
     '{{KW|Retain}}.<br>Gain (12;16) {{KW|Block}}.<br>{{KW|Exhaust}}.'),
    # ---- Special Attack ----------------------------------------------------------------
    ('bite', 'Bite', 'Colorless', 'Attack', 'Special', '1', None,
     'Deal (7;8) damage.<br>Heal (2;3) HP.'),
    ('expunger', 'Expunger', 'Colorless', 'Attack', 'Special', '1', None,
     'Deal (9;15) damage X times.'),
    ('ritual_dagger', 'Ritual Dagger', 'Colorless', 'Attack', 'Special', '1', None,
     'Deal 15 damage. If {{KW|Fatal}}, permanently increase this card\'s damage by (3;5).'
     '<br>{{KW|Exhaust}}.'),
    ('shiv', 'Shiv', 'Colorless', 'Attack', 'Special', '0', None,
     'Deal (4;6) damage.<br>{{KW|Exhaust}}.'),
    ('smite', 'Smite', 'Colorless', 'Attack', 'Special', '1', None,
     '{{KW|Retain}}.<br>Deal (12;16) damage.<br>{{KW|Exhaust}}.'),
    ('through_violence', 'Through Violence', 'Colorless', 'Attack', 'Special', '0', None,
     '{{KW|Retain}}.<br>Deal (20;30) damage.<br>{{KW|Exhaust}}.'),
    # ---- Special Power -----------------------------------------------------------------
    ('become_almighty', 'Become Almighty', 'Colorless', 'Power', 'Special', '?', None,
     'UNVERIFIED: the wiki data module did not include this entry. Fetch the page before use.'),
    ('live_forever', 'Live Forever', 'Colorless', 'Power', 'Special', '?', None,
     'Gain (6;8) {{KW|Plated Armor}}. UNVERIFIED: the cost was not in the fetched excerpt.'),
    ('omega', 'Omega', 'Colorless', 'Power', 'Special', '3', None,
     'At the end of your turn, deal (50;60) damage to ALL enemies.'),
    # ---- Curse -------------------------------------------------------------------------
    ('clumsy', 'Clumsy', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>{{KW|Ethereal}}.'),
    ('curse_of_the_bell', 'Curse of the Bell', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>Cannot be removed from your deck.'),
    ('decay', 'Decay', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>At the end of your turn, take 2 damage.'),
    ('necronomicurse', 'Necronomicurse', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>There is no escape from this curse.'),
    ('normality', 'Normality', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>You cannot play more than 3 cards this turn.'),
    ('pain', 'Pain', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>While in hand, lose 1 HP when other cards are played.'),
    ('parasite', 'Parasite', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>If transformed or removed from your deck, lose 3 Max HP.'),
    ('pride', 'Pride', 'Curse', 'Curse', 'Curse', '1', None,
     '{{KW|Innate}}.<br>At the end of your turn, put a copy of this card on top of your '
     'draw pile.<br>{{KW|Exhaust}}.'),
    ('regret', 'Regret', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>At the end of your turn, lose HP equal to the number of cards '
     'in your hand.'),
    ('shame', 'Shame', 'Curse', 'Curse', 'Curse', 'Unplayable', None,
     '{{KW|Unplayable}}.<br>At the end of your turn, gain 1 {{KW|Frail}}.'),
]


def main():
    written = 0
    skipped = 0
    for cid, name, color, ctype, rarity, cost, cost_plus, desc in DATA:
        path = os.path.join(OUT, cid + '.txt')
        if os.path.exists(path):
            # 已有的 dump 是**整页原文**（比数据模块富），绝不覆盖。
            skipped += 1
            continue
        cost_line = '| Cost          = %s\n' % cost if cost not in ('Unplayable',) else ''
        unplayable = '| Unplayable    = yes\n' if cost == 'Unplayable' else ''
        plus = '| CostPlus      = %s\n' % cost_plus if cost_plus else ''
        text = (
            '{{Card Infobox\n'
            '| Name          = %s\n'
            '| Color         = %s\n'
            '| Type          = %s\n'
            '| Rarity        = %s\n'
            '%s%s%s'
            '| Description   = %s\n'
            '}}\n'
            '\n'
            '<!-- §243：由 native/fetch_colorless_dumps.py 从\n'
            '     slaythespire.wiki.gg/wiki/Module:Cards/data 转写（`[a|b]` → `(a;b)`，\n'
            '     `$Keyword` → `{{KW|Keyword}}`）。数字仍以本行为准；实现前请核对\n'
            '     UNVERIFIED 标注。 -->\n'
            % (name, color, ctype, rarity, cost_line, plus, unplayable, desc)
        )
        io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
        written += 1
    print('dumps written %d, skipped(existing) %d, total table %d'
          % (written, skipped, len(DATA)))


main()
