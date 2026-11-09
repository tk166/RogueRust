"""§316（二）：清单 —— Act 3 的池子重排 + Repulsor / Exploder。

清单要动的地方：
* `INV_WEAK_POOL`：删 `enc_byrds` / `enc_spiker`（前者挂错幕、后者只作为 Shapes 的一员出现），
  加 `enc_darklings_hard` / `enc_jaw_worm_horde` / `enc_three_shapes` / `enc_four_shapes` /
  `enc_spheric_and_two_shapes`（组合槽写成 `a|b|c` 的**排序后**集合，与 §277 的写法一致）；
* `INV_ACT_TABLES['Weak3']`：wiki 的九条；
* `INV_MONSTERS` / `INV_ACTIONS` / `INV_ASC_VARIANTS` / `INV_NO_ASC` / `INV_ASC_HP` /
  `INV_NO_ASC_HP`：两个新怪与四个新招；
* 三处数量：monsters 57、encounters 61。
"""
import io

CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

PATCHES = [
    # 数量
    ('    "monsters": 55,', '    "monsters": 57,'),
    ('    "encounters": 54,', '    "encounters": 61,'),
    # 怪物表
    ('INV_MONSTERS = [',
     '''INV_MONSTERS = [
    # §316：Act 3 的 Shapes（wiki `Shapes`）：Repulsor 29-35（A7 31-38）、Exploder **30**。
    ("repulsor", 29, 35, ["repulsor.daze", "repulsor.attack"]),
    ("exploder", 30, 30, ["exploder.attack", "exploder.explode"]),'''),
    # 动作表（意图 + 事实）
    ('INV_ACTIONS = {',
     '''INV_ACTIONS = {
    # §316：Shapes。Daze 往**抽牌堆**塞 2 张 Dazed；Explode 打完 30 点自己死。
    "repulsor.daze": ("Debuff", [("card", "dazed", 2, "DrawPile", "event")]),
    "repulsor.attack": ("Attack", [("damage", 11, "event")]),
    "exploder.attack": ("Attack", [("damage", 9, "event")]),
    "exploder.explode": ("Unknown", [("damage", 30, "event"), ("destroy", "source")]),'''),
    # 升阶数字
    ('INV_ASC_VARIANTS = {',
     '''INV_ASC_VARIANTS = {
    # §316：Repulsor Attack 11→13、Exploder Attack 9→11（wiki 的 `{{Asc|2|…}}`）。
    'repulsor.attack': [(2, [('damage', 13, 'event')])],
    'exploder.attack': [(2, [('damage', 11, 'event')])],'''),
    # 无升阶数字的动作
    ('INV_NO_ASC = {',
     '''INV_NO_ASC = {
    # §316：Daze 只有 "Adds 2 Dazed"，Explode 只有 "Deals 30 damage. Dies." —— 都没有 A 档。
    'repulsor.daze': 'wiki Shapes: Daze has no A-row',
    'exploder.explode': 'wiki Shapes: Explode has no A-row', '''),
    # 升阶血量
    ("    # §313: Centurion 78-83 / Mystic 50-58（下界 78 / 50）。",
     """    # §316: Repulsor 29-35 → A7 31-38（下界 31）。
    'repulsor': 31,
    # §313: Centurion 78-83 / Mystic 50-58（下界 78 / 50）。"""),
    # 血量不随升阶变的怪物
    ("    'spheric_guardian': 'wiki Spheric Guardian: HP 20, no AscHP column',",
     """    'spheric_guardian': 'wiki Spheric Guardian: HP 20, no AscHP column',
    # §316：Exploder 的 wiki 是 `HP 30 | 30-35 7` —— A7 那一列是**范围**，下界仍是 30，
    # 所以"钉一条 A7 行"只会把 30 再写一遍（判据会拒："identical to the base"）。
    'exploder': 'wiki Shapes: Exploder HP 30, the A7 column is a 30-35 range',
    """),
    # 池子成员 + 敌人组成
    ('    "enc_snake_plant": ["snake_plant"],',
     '''    "enc_snake_plant": ["snake_plant"],
    # §316：Act 3 的池子（wiki `The_Beyond`）。组合槽写成排序后的 `a|b|c`。
    "enc_three_shapes": ["exploder|repulsor|spiker", "exploder|repulsor|spiker",
                         "exploder|repulsor|spiker"],
    "enc_four_shapes": ["exploder|repulsor|spiker", "exploder|repulsor|spiker",
                        "exploder|repulsor|spiker", "exploder|repulsor|spiker"],
    "enc_spheric_and_two_shapes": ["spheric_guardian", "exploder|repulsor|spiker",
                                   "exploder|repulsor|spiker"],
    "enc_jaw_worm_horde": ["jaw_worm", "jaw_worm", "jaw_worm"],
    "enc_darklings_hard": ["darkling", "darkling", "darkling"],'''),
    # `enc_darklings` 从 2 只改成 3 只
    ('    "enc_darklings": ["darkling", "darkling"],',
     '    "enc_darklings": ["darkling", "darkling", "darkling"],'),
    # 池子表
    ('''    "Weak3": ["enc_byrds", "enc_darklings", "enc_maw", "enc_orb_walker", "enc_spiker",
              "enc_spire_growth"],''',
     '''    # §316：wiki `The_Beyond` 的 Easy（权重 2）+ Hard（权重 1），×10 取整。
    # `Transient` 未做（要"Fading"与伤害递增两条新机制），见 `docs/sts-wiki-gap.md` §D.5。
    "Weak3": ["enc_darklings", "enc_orb_walker", "enc_three_shapes",
              "enc_four_shapes", "enc_maw", "enc_spheric_and_two_shapes",
              "enc_darklings_hard", "enc_spire_growth", "enc_jaw_worm_horde"],'''),
]


def main():
    text = io.open(CHECK, encoding='utf-8').read()
    for old, new in PATCHES:
        assert text.count(old) == 1, (old[:60], text.count(old))
        text = text.replace(old, new)
    # `enc_byrds` 不再存在 ⇒ 它的清单条目要删掉（否则"清单里的遭遇不存在"会红）。
    old_byrds = ('    # §311：wiki 的 "3 Byrds" 是**三只**（这一条内容原先只写了一只，'
                 '同时影响第三幕的池子）。\n    "enc_byrds": ["byrd", "byrd", "byrd"],\n')
    assert text.count(old_byrds) == 1, 'byrds entry'
    text = text.replace(old_byrds, '')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('inventory extended for act 3')


main()
