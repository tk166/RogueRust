"""§314（二）：把 Mugger 与 `2 Thieves` 登记进独立清单。

动的地方与上一节同构：怪物表 / 动作表（意图 + 事实）/ 升阶决策与数字 / 升阶血量 /
池子成员 / 遭遇的敌人组成 / 三处数量。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

PATCHES = [
    # 数量
    ('    "monsters": 54,', '    "monsters": 55,'),
    ('    "encounters": 52,', '    "encounters": 53,'),
    # 怪物表
    ('INV_MONSTERS = [',
     '''INV_MONSTERS = [
    # §314: Act 2 的 Mugger —— wiki `Thieves`："Mugger has the same pattern as Looter."
    # 数字：HP 48-52（A7 50-54）、Mug 10（A2 11）、Lunge 16（A2 18）、Smoke Bomb 11（A17 17）。
    ("mugger", 48, 52, ["mugger.mug", "mugger.lunge", "mugger.smoke_bomb", "mugger.escape"]),'''),
    # 动作表
    ('INV_ACTIONS = {',
     '''INV_ACTIONS = {
    # §314: Mugger —— 与 Looter 同一套形状（`stolen_gold` 每次都 +15，A17 起 +20 在下面那张表里）。
    "mugger.mug": ("Attack", [("damage", 10, "event"),
                              ("counter", "stolen_gold", 15, True, "source")]),
    "mugger.lunge": ("Attack", [("damage", 16, "event"),
                                ("counter", "stolen_gold", 15, True, "source")]),
    "mugger.smoke_bomb": ("Defend", [("block", 11, "source")]),
    "mugger.escape": ("Special", [("carry", "stolen_gold", "source"), ("destroy", "source")]),'''),
    # 升阶数字：Mugger 的三招
    ("    'looter.mug': [(2, [('damage', 11, 'event'),",
     """    # §314: Mugger —— 与 Looter 同一组阈值（A2 伤害、A17 偷钱），数字是 wiki 的。
    'mugger.mug': [(2, [('damage', 11, 'event'),
                        ('counter', 'stolen_gold', 15, True, 'source')]),
                   (17, [('damage', 11, 'event'),
                         ('counter', 'stolen_gold', 20, True, 'source')])],
    'mugger.lunge': [(2, [('damage', 18, 'event'),
                          ('counter', 'stolen_gold', 15, True, 'source')]),
                     (17, [('damage', 18, 'event'),
                           ('counter', 'stolen_gold', 20, True, 'source')])],
    'mugger.smoke_bomb': [(17, [('block', 17, 'source')])],
    'looter.mug': [(2, [('damage', 11, 'event'),"""),
    # 升阶决策：Escape 没有数字
    ("""    'looter.smoke_bomb': 'wiki Thieves: 6 Block, no A-row',
    'looter.escape': 'wiki Thieves: Escape has no numbers',""",
     """    'looter.smoke_bomb': 'wiki Thieves: 6 Block, no A-row',
    'looter.escape': 'wiki Thieves: Escape has no numbers',
    # §314
    'mugger.escape': 'wiki Thieves: Escape has no numbers',"""),
    # 升阶血量
    ("    # §313: Centurion 78-83 / Mystic 50-58（下界 78 / 50）。",
     "    # §314: Mugger 50-54（下界 50）。\n    'mugger': 50,\n"
     "    # §313: Centurion 78-83 / Mystic 50-58（下界 78 / 50）。"),
    # 池子成员 + 敌人组成
    ('    "enc_centurion_and_mystic": ["centurion", "mystic"],',
     '''    "enc_centurion_and_mystic": ["centurion", "mystic"],
    # §314：wiki 的 Details 列 —— 1 Looter 在左、1 Mugger 在右。
    "enc_two_thieves": ["looter", "mugger"],'''),
    ('              "enc_snake_plant", "enc_centurion_and_mystic"],',
     '              "enc_snake_plant", "enc_centurion_and_mystic", "enc_two_thieves"],'),
]


def main():
    text = io.open(CHECK, encoding='utf-8').read()
    for old, new in PATCHES:
        assert text.count(old) == 1, (old[:60], text.count(old))
        text = text.replace(old, new)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('inventory extended for mugger / two thieves')


main()
