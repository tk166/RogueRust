"""§315（一）：`MaxHealthAsc` 的档位是**这只怪自己的**，不是池子的。

## 原来的假设错在哪

`check_ascension_health` 现在这样推档位：

    精英池 ⇒ A8、Boss 池 ⇒ A9、其余 ⇒ A7

多数怪物确实如此（普通怪 A7、精英 A8、Boss A9），但 **Sentry 是反例**：它是 Act 1 的**精英**
（wiki：38-42，**A8** 起 39-45），同时又是 Act 2 的**普通**敌人 —— 同一只怪、同一张 wiki 表。
按池子档位钉，同一条怪物记录会被要求**同时**是 A7 与 A8（两条不可能同时成立），于是
`Sentry and Spheric Guardian` 一直做不了。

## 改法

钉的档位改成"**wiki 说的那一档**"：默认仍按池子推（存量 100 多条记录一个字都不用改），
但对 Sentry 这种"表里的档位与池子不一致"的怪物，用 `INV_ASC_HP_LEVEL` 显式写出它的档位。
于是同一条 `{A8, 39}` 在精英池与普通池的**两处记录里都是正确答案**。

第 7 档以下没有这一行 ⇒ 内核不覆盖（`build_fight` 的 `+10%` 回退在跑层是 0），所以
Act 2 的 Sentry 在 A7 仍是 38、A8 起 39 —— 与 wiki 一致。
"""
import io

PATH = 'D:/Vibe/sts-tui/native/sts_content_check.py'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch('''# §207: monsters whose ENCT record has **no** `MaxHealthAsc`, with the wiki reason.''',
'''# §315: 钉的档位与**池子档位**不一致的怪物（默认按池子推：普通 A7 / 精英 A8 / Boss A9）。
#
# `Sentry` 是唯一的一个：wiki 「38-42，**A8** 起 39-45」—— 它在 Act 1 是**精英**（A8 对得上），
# 在 Act 2 又是**普通**敌人（池子档位 A7）。同一只怪、同一张表，所以档位只能按**它自己**钉。
INV_ASC_HP_LEVEL = {
    'sentry_1': 8,
    'sentry_2': 8,
    'sentry_3': 8,
}

# §207: monsters whose ENCT record has **no** `MaxHealthAsc`, with the wiki reason.''')

    patch('''            rows = enemy.get("MaxHealthAsc")
            if not rows:
                fail("asc.hp." + monster, "no MaxHealthAsc (the row still uses the +10% model)")
                continue
            if len(rows) != 1:
                fail("asc.hp." + monster, "expected exactly one A%d row, got %r" % (level, rows))
                continue
            row = rows[0]
            if row.get("AscensionMin") != level:
                fail("asc.hp." + monster,
                     "pinned at A%s, but this encounter pays A%d"
                     % (row.get("AscensionMin"), level))''',
'''            # §315：**档位来自 wiki 的那张表，不来自池子**（见 `INV_ASC_HP_LEVEL` 的注释）。
            # 默认仍按池子推，于是存量记录一个字都不用改；只有"同一只怪跨档位"的那几个才要写。
            pin_level = INV_ASC_HP_LEVEL.get(monster, level)
            rows = enemy.get("MaxHealthAsc")
            if not rows:
                fail("asc.hp." + monster, "no MaxHealthAsc (the row still uses the +10% model)")
                continue
            if len(rows) != 1:
                fail("asc.hp." + monster, "expected exactly one A%d row, got %r" % (pin_level, rows))
                continue
            row = rows[0]
            if row.get("AscensionMin") != pin_level:
                fail("asc.hp." + monster,
                     "pinned at A%s, the wiki's `AscHP` row is A%d"
                     % (row.get("AscensionMin"), pin_level))''')
    print('checker: pin level comes from the monster')


main()
