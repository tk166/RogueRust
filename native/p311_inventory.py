"""§311（二）：把 Act 2 的六条新遭遇与新怪物登记进 `sts_content_check.py` 的清单。

这份清单是**独立的口径**（把它当成 wiki 的投影）：它不认识内容里"我写了什么"，只认识
"wiki 里有什么"。所以加内容必须同时加清单 —— 否则闸门红得对（"内容里有一条我在
wiki 里找不到的遭遇"），而如果反过来只改清单不改内容，那才是把闸门弄坏。

三条要登记的东西：
1. `INV_WEAK_POOL`：六条新遭遇的敌人组成（`enc_byrds` 的期望值改成 3 只 —— 顺手修的那条）；
2. `INV_ACT_TABLES['Weak2']`：新的池子（10 条）；
3. `INV_WEAK_WEIGHT` 那条注释（Act 2 的权重不再是 50/50/50）。
"""
import io

PATH = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # 1. 敌人组成
    patch('''    "enc_byrds": ["byrd"],''',
'''    # §311：wiki 的 "3 Byrds" 是**三只**（这一条内容原先只写了一只，同时影响第三幕的池子）。
    "enc_byrds": ["byrd", "byrd", "byrd"],''')

    patch('''    "enc_snecko": ["snecko"],
}''',
'''    "enc_snecko": ["snecko"],
    # §311：Act 2 的其余六条（`The_City` 页的 Easy/Hard 池，两处来源核对）。
    "enc_spheric_guardian": ["spheric_guardian"],
    # `enc_two_thieves`（1 Looter + 1 Mugger）还没做：Mugger 是**新怪物**，它的行动序列在 wiki
    # 上只有一张表（没有像 Looter 那样的逐步文字规则），所以留到下一节把 Mugger 的规则核对清楚。
    "enc_chosen_and_byrd": ["chosen", "byrd"],
    "enc_cultist_and_chosen": ["cultist", "chosen"],
    "enc_three_cultists": ["cultist", "cultist", "cultist"],
    "enc_parasite_and_fungi": ["shelled_parasite", "fungi_beast"],
    "enc_sentry_and_spheric": ["sentry_1", "spheric_guardian"],
}''')

    # 2. 池子
    patch('''    "Weak2": ["enc_chosen", "enc_shelled_parasite",
              # §282: Act 2 的普通怪 Snecko（`Confusion` 的载体）。
              "enc_snecko"],''',
'''    # §311：Act 2 的 13 条里做了 10 条（`snake_plant` / `centurion + mystic` 还要新机制，
    # 见 `docs/sts-wiki-gap.md` §D.3）。权重是 wiki 的（×5 取整）。
    "Weak2": ["enc_spheric_guardian", "enc_chosen", "enc_shelled_parasite", "enc_byrds",
              "enc_chosen_and_byrd", "enc_cultist_and_chosen", "enc_sentry_and_spheric",
              # §282: Act 2 的普通怪 Snecko（`Confusion` 的载体）。
              "enc_snecko", "enc_three_cultists", "enc_parasite_and_fungi"],''')

    patch('''INV_WEAK_WEIGHT = 100  # inv:§5.2 权重之和 100（6 个遭遇按 20/16/16/16/16/16 分）''',
'''INV_WEAK_WEIGHT = 100  # inv:§5.2 Act 1 的权重之和 100（6 个遭遇按 20/16/16/16/16/16 分）
# §311：Act 2 的权重是 wiki 的 Easy 2 / Hard 2,3,2,6,4,6,3,3 乘 5 取整（缺的两条不占位）。''')
    print('inventory updated')


main()
