"""§324 内容门：J.A.X. 两行卡 + `transform_choose:` 词表 + 那张独立的卡 wiki 表。"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── 1. 卡表两行 ────────────────────────────────────────────────────────────────
t = sub(t, 'INV_CARDS = {', '''INV_CARDS = {
    # §324：Augmenter 的 J.A.X.（0 费无色特殊技能：失 3 血、+2 力量；`+` 行 +3）。
    "jax": {"Cost": 0, "Tags": ["skill", "colorless"],
            "Facts": [["hp", 3, "source"], ["status", "standard.strength", 2, "source"]]},
    "jax+": {"Cost": 0, "Tags": ["skill", "colorless"],
             "Facts": [["hp", 3, "source"], ["status", "standard.strength", 3, "source"]]},''',
        'INV_CARDS')

# ── 3. 词表分支：验张数 ────────────────────────────────────────────────────────
t = sub(t, '''                if kind == "remove_card_random":''',
        '''                if kind == "transform_choose":
                    # §324：`augmenter` 的 `[Become Test Subject]` —— 选 n 张各改造一次。
                    if not (payload or "").isdigit() or not (1 <= int(payload) <= 5):
                        fail(where, "transform_choose 的张数 %r 不在 1..=5" % (payload,))
                    if entry.get("Amount") not in (0, None, int(payload or 0)):
                        fail(where, "transform_choose 的 Amount 要么缺省、要么与词里的张数相同")
                    counts["effects"] += 1
                    continue
                if kind == "remove_card_random":''',
        'transform_choose branch')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate updated')
