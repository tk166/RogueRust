"""§319：内容门（`sts_content_check.py`）的词表 —— 效果 `remove_card_random:<kind>` 与条件 `card_tag`。

这是**第二份**词表（第一份是 `rd-core::run_expr::KINDS` 与 `rd-run::state::CardKind::from_wire`），
而这个文件的存在理由正是"第二意见"：两边不一致时它在这里红。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """                  # §287：`card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"（`Wing Statue`）。
                  "card_damage")""",
        """                  # §287：`card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"（`Wing Statue`）。
                  "card_damage",
                  # §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自
                  # 按类型上锁）。`Id` 必须是下面 `CARD_KIND_NAMES` 里的一个。
                  "card_tag")""",
        'REQUIRES_KINDS')

t = sub(t, """EVENT_PERCENT_EFFECTS = ("damage_pct", "max_hp_pct")""",
        """EVENT_PERCENT_EFFECTS = ("damage_pct", "max_hp_pct")
# §319：`remove_card_random:<kind>` 的载荷词表 —— 与 `rd-run::state::CardKind::from_wire`
# 逐字对应（那是第一份；这一份是第二意见）。
CARD_KIND_NAMES = ("attack", "skill", "power", "status", "curse", "other")""",
        'CARD_KIND_NAMES')

t = sub(t, """                if kind == "relic_random":""",
        """                if kind == "remove_card_random":
                    # §319：`falling` —— "Lose (a random <type> card)"。载荷是**类型**，
                    # 不是卡 id：拼错的类型在内核里会解析失败（内容报错），这里先拦。
                    if payload not in CARD_KIND_NAMES:
                        fail(where, "remove_card_random 的类型 %r 不在 %s 里"
                             % (payload, " / ".join(CARD_KIND_NAMES)))
                    if entry.get("Amount") not in (0, None):
                        fail(where, "remove_card_random 的 Amount 必须是 0（类型在词里）")
                    counts["effects"] += 1
                    continue
                if kind == "relic_random":""",
        'remove_card_random branch')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('sts_content_check.py patched')
