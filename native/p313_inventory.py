"""§313（三）：清单 —— 新选择器、新条件、两个怪物、六个动作、一条新遭遇。

检查器有四张"独立口径"的表要动：
1. `tgt()`：`sel.*` → 事实里的短标签（未知选择器**报错**，不许猜）；
2. `INTENT_CONDITIONS`：内核认识的条件名；
3. `INV_MONSTERS` / `INV_ACTIONS`：怪物的血量与招式、每个招式的意图 + 事实；
4. `INV_ASC_VARIANTS` / `INV_NO_ASC` / `INV_ASC_HP`：升阶数字与血量；
5. `INV_WEAK_POOL` / `INV_ACT_TABLES['Weak2']` / 两处数量。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

PATCHES = [
    # 1. 选择器标签：把定义 id 也写进标签 —— 事实里"给谁 15 块"才是完整的
    ('''        "sel.allAllies": "allAllies",
    }''',
     '''        "sel.allAllies": "allAllies",
        # §313：按**定义**挑一只友军。标签带上定义 id —— `block 15 alliesWithDefinition:mystic`
        # 与 `...:centurion` 是两条不同的承诺，只写选择器类型会把它们合成一个事实。
        "sel.alliesWithDefinition": "alliesWithDefinition:%s"
        % selector["value"]["CombatantDefinitionId"],
    }'''),
    # 2. 新条件
    ('''INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",''',
     '''INTENT_CONDITIONS = ("intent.healthPercent", "intent.round", "intent.selfHasStatus",
                     # §313：谁会治疗 —— "自己的阵营里有人缺了 ≥ N 血"。
                     "intent.allyMissingHealth",'''),
    # 3. 数量
    ('    "monsters": 52,', '    "monsters": 54,'),
    ('    "encounters": 51,', '    "encounters": 52,'),
    # 4. 怪物表
    ('INV_MONSTERS = [',
     '''INV_MONSTERS = [
    # §313: Act 2 的 Centurion / Mystic（wiki 76-80 / 48-56，A7 78-83 / 50-58）。
    ("centurion", 76, 80, ["centurion.slash", "centurion.protect", "centurion.fury"]),
    ("mystic", 48, 56, ["mystic.attack", "mystic.buff", "mystic.heal"]),'''),
    # 5. 动作表（意图 + 事实）
    ('INV_ACTIONS = {',
     '''INV_ACTIONS = {
    # §313: Centurion。`Protect` 的两个分支各是一条事实：给 Mystic 15 块 / 独自时给自己 15 块。
    "centurion.slash": ("Attack", [("damage", 12, "event")]),
    "centurion.protect": ("Defend", [("block", 15, "alliesWithDefinition:mystic"),
                                     ("block", 15, "source")]),
    "centurion.fury": ("Attack", [("damage", 6, "event"), ("damage", 6, "event"),
                                  ("damage", 6, "event")]),
    # §313: Mystic。`Buff`/`Heal` 目标是**全体敌人**（含自己）。
    "mystic.attack": ("Attack", [("damage", 8, "event"),
                                 ("status", "standard.frail", 2, "event")]),
    "mystic.buff": ("Buff", [("status", "standard.strength", 2, "allAllies")]),
    "mystic.heal": ("Buff", [("heal", 16, "allAllies")]),'''),
    # 6. 升阶数字
    ('INV_ASC_VARIANTS = {',
     '''INV_ASC_VARIANTS = {
    # §313: Centurion（A2 伤害 +2/+1，A17 Protect 15→20）与 Mystic（A2 Attack 9 / Buff 3，
    # A17 Buff 4 / Heal 20）。
    'centurion.slash': [(2, [('damage', 14, 'event')])],
    'centurion.protect': [(17, [('block', 20, 'alliesWithDefinition:mystic'),
                                ('block', 20, 'source')])],
    'centurion.fury': [(2, [('damage', 7, 'event'), ('damage', 7, 'event'),
                            ('damage', 7, 'event')])],
    'mystic.attack': [(2, [('damage', 9, 'event'),
                           ('status', 'standard.frail', 2, 'event')])],
    'mystic.buff': [(2, [('status', 'standard.strength', 3, 'allAllies')]),
                    (17, [('status', 'standard.strength', 4, 'allAllies')])],
    'mystic.heal': [(17, [('heal', 20, 'allAllies')])],'''),
    # 7. 池子成员 + 敌人组成
    ('    "enc_snake_plant": ["snake_plant"],',
     '''    "enc_snake_plant": ["snake_plant"],
    # §313：Centurion 在前、Mystic 在后（wiki 的 Details 列：1 Centurion + 1 Mystic）。
    "enc_centurion_and_mystic": ["centurion", "mystic"],'''),
    ('              "enc_snake_plant"],',
     '''              "enc_snake_plant", "enc_centurion_and_mystic"],'''),
    # 8. 升阶血量
    ("    # §312: Snake Plant 的 wiki `AscHP` 是 78-82（下界 78）。",
     "    # §313: Centurion 78-83 / Mystic 50-58（下界 78 / 50）。\n"
     "    'centurion': 78, 'mystic': 50,\n"
     "    # §312: Snake Plant 的 wiki `AscHP` 是 78-82（下界 78）。"),
]


def main():
    text = io.open(CHECK, encoding='utf-8').read()
    for old, new in PATCHES:
        assert text.count(old) == 1, (old[:60], text.count(old))
        text = text.replace(old, new)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('inventory extended for centurion / mystic')


main()
