"""§312（二）：把 Malleable 与 Snake Plant 登记进独立清单。

清单要动的地方（都是既有闸门逐条要求的）：
`INV_STATUSES`（id + 被动修饰器）、`check_statuses` 的"只有触发器"分支（含期望的事件列表）、
`INV_MONSTERS`、`INV_ACTIONS`（意图 + 事实）、`INV_ASC_VARIANTS`（A2 的 8×3）、`INV_NO_ASC`
（Spores 没有升阶数字）、`INV_WEAK_POOL`、`INV_ACT_TABLES['Weak2']`、以及两处数量。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

PATCHES = [
    # 数量
    ('    "monsters": 51,', '    "monsters": 52,'),
    ('    "encounters": 50,', '    "encounters": 51,'),
    # 怪物表
    ('INV_MONSTERS = [',
     '''INV_MONSTERS = [
    # §312: Act 2 的 Snake Plant —— 75-79 血（A7 78-82），Malleable 3，两招。
    ("snake_plant", 75, 79,
     ["snake_plant.chomp_chomp", "snake_plant.enfeebling_spores"]),'''),
    # 动作表
    ('INV_ACTIONS = {',
     '''INV_ACTIONS = {
    # §312: Snake Plant（wiki `Snake Plant` 页 + `SlaySpireDB`）。
    "snake_plant.chomp_chomp": ("Attack", [("damage", 7, "event"), ("damage", 7, "event"),
                                          ("damage", 7, "event")]),
    "snake_plant.enfeebling_spores": ("Debuff", [("status", "standard.frail", 2, "event"),
                                                 ("status", "standard.weak", 2, "event")]),'''),
    # 状态表（无被动修饰器：行为全在触发器里）
    ('INV_STATUSES = {',
     '''INV_STATUSES = {
    # §312: Malleable —— 行为全在触发器里（`DamageTaken` + `TurnStarted`），没有被动修饰器。
    "standard.malleable": [],'''),
    # `INV_STATUSES` 里"只有触发器"的分支：加 id
    ('                     "standard.mummified_hand"):',
     '''                     "standard.mummified_hand",
                     # §312
                     "standard.malleable"):'''),
    # 期望的触发器事件
    ('            expected = {"standard.thorns": ["DamageTaken"],',
     '''            expected = {"standard.thorns": ["DamageTaken"],
                        # §312: 挨打长格挡（`DamageTaken`）+ 每回合清零（`TurnStarted`）。
                        "standard.malleable": ["DamageTaken", "TurnStarted"],'''),
    # 升阶数字：Chomp Chomp 的 A2 是 8×3
    ('INV_ASC_VARIANTS = {',
     '''INV_ASC_VARIANTS = {
    # §312: Snake Plant 的 Chomp Chomp 在 A2 起是 8×3（wiki `{{Asc|2|8×3}}`）。
    'snake_plant.chomp_chomp': [(2, [('damage', 8, 'event'), ('damage', 8, 'event'),
                                    ('damage', 8, 'event')])],'''),
    # Spores 没有升阶数字
    ('INV_NO_ASC = {',
     '''INV_NO_ASC = {
    # §312: `Enfeebling Spores` 只有 "2 Frail and 2 Weak" 一行，没有 A 档。
    'snake_plant.enfeebling_spores': 'wiki Snake Plant: Spores have no A-row', '''),
    # 池子成员 + 敌人组成
    ('    "enc_spheric_guardian": ["spheric_guardian"],',
     '''    "enc_spheric_guardian": ["spheric_guardian"],
    # §312：Snake Plant 独自出现（wiki Hard 池，权重 6）。
    "enc_snake_plant": ["snake_plant"],'''),
    ('              "enc_snecko", "enc_three_cultists", "enc_parasite_and_fungi"],',
     '''              "enc_snecko", "enc_three_cultists", "enc_parasite_and_fungi",
              "enc_snake_plant"],'''),
]


def main():
    text = io.open(CHECK, encoding='utf-8').read()
    for old, new in PATCHES:
        assert text.count(old) == 1, (old[:60], text.count(old))
        text = text.replace(old, new)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('inventory extended for malleable / snake_plant')


main()
