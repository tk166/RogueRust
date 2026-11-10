"""§327 修正自己刚犯的错：检查器里有**两份** `INV_ASC_HP_LEVEL`。

3201 那份是按**池子**的（`{'Elite': 8, 'Boss': 9}`，被 §315 之后的那份取代但没删），
3272 那份才是真正被 `check_ascension_hp` 用的**按怪物**表。我在 3210 又加了一份
"按怪物"的 —— 那就成了三份词表，正是"同一个词表被两处认识就一定漂"的形状。

修法：删掉我刚加的那一份，把 slaver 两条写进**真正被用**的那份（3272）。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ① 删掉我自己加的那份（在 §187 那段下面）。
t = sub(t, """
# §327：**档位属于怪物，不属于池子**。默认按池子推（普通 A7 / 精英 A8 / Boss A9）是因为
# 绝大多数怪物只出现在一个档位里；但 wiki 的 `AscHP` 行是按**怪物自己**的 `Type` 定的
# （`Enemy Infobox` 的 `| Type = Normal`），所以"普通怪出现在精英遭遇里"就必须单独钉。
#
#   * `Sentry`（§315）：精英怪出现在 Act 2 的**普通**池里 ⇒ 钉 A8；
#   * `Blue Slaver` / `Red Slaver`（§327）：普通怪出现在 Act 2 的**精英**池（`Slavers`）里
#     ⇒ 钉 A7（wiki.gg 与 SlaySpireDB 都写 "Ascension 7 and up"）。
INV_ASC_HP_LEVEL_BY_MONSTER = {
    'sentry_1': 8, 'sentry_2': 8, 'sentry_3': 8,
    'blue_slaver': 7, 'slaver_red': 7,
}""", '', 'drop my duplicate')

# ② 真正被用的那份：补 slaver 两条 + 把注释写清"档位属于怪物"。
t = sub(t, """# §315: 钉的档位与**池子档位**不一致的怪物（默认按池子推：普通 A7 / 精英 A8 / Boss A9）。
#
# `Sentry` 是唯一的一个：wiki 「38-42，**A8** 起 39-45」—— 它在 Act 1 是**精英**（A8 对得上），
# 在 Act 2 又是**普通**敌人（池子档位 A7）。同一只怪、同一张表，所以档位只能按**它自己**钉。
INV_ASC_HP_LEVEL = {
    'sentry_1': 8,
    'sentry_2': 8,
    'sentry_3': 8,
}""",
        """# 钉的档位与**池子档位**不一致的怪物（默认按池子推：普通 A7 / 精英 A8 / Boss A9）。
#
# ⚠️ 根子上的规则是：wiki 的 `AscHP` 行按**怪物自己**的 `Type` 定（`| Type = Normal` ⇒ A7），
# 而"按池子推"只是因为它俩绝大多数时候一致。不一致时就必须钉：
#
#   * `Sentry`（§315）：精英怪出现在 Act 2 的**普通**池里 ⇒ 钉 A8
#     （wiki 「38-42，**A8** 起 39-45」）。
#   * `Blue Slaver` / `Red Slaver`（§327）：**普通**怪出现在 Act 2 的**精英**池（`Slavers`）里
#     ⇒ 钉 A7（wiki.gg「46-50 | 48-52 | 7」与 SlaySpireDB「Ascension 7 and up」两个来源）。
INV_ASC_HP_LEVEL = {
    'sentry_1': 8,
    'sentry_2': 8,
    'sentry_3': 8,
    'blue_slaver': 7,
    'slaver_red': 7,
}""",
        'real dict')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('checker: one table only, slavers pinned at A7')
