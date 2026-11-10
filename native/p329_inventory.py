"""§329 检查器清单同步（照抄它报出来的 facts —— 那份清单的职责就是"内容当前是什么"，
而"这是不是 wiki 说的"由 §328 的 `[7b]` 与 `INV_ASC_VARIANTS` 各自负责）。
"""

import io

PATH = 'native/sts_content_check.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ① rebirth：+ cleanse（wiki "Removes all Debuffs"）
t = sub(t, """    "awakened_one.rebirth": ("Special", [("heal", ("expr", "max"), "source"),
                                         ("modify", "standard.curiosity", -99, "source"),""",
        """    # §329：wiki "Heals to full HP. **Removes all Debuffs**. Loses Curiosity."
    "awakened_one.rebirth": ("Special", [("heal", ("expr", "max"), "source"),
                                         ("cleanse", "source"),
                                         ("modify", "standard.curiosity", -99, "source"),""",
        'rebirth cleanse')

# ② haste 的 A19 变体：+ cleanse
t = sub(t, """    'time_eater.haste': [(19, [('heal', ('expr', 'max'), 'source'),
                               ('block', 32, 'source'),""",
        """    # §329：wiki "Removes all Debuffs. Heals to 50% HP. (A19: gains 32 Block.)"
    'time_eater.haste': [(19, [('heal', ('expr', 'max'), 'source'),
                               ('cleanse', 'source'),
                               ('block', 32, 'source'),""",
        'haste cleanse')

# ③ haste 的基础档（在 INV_ACTIONS 里）
t = sub(t, """    "time_eater.haste": ("Buff", [("heal", ("expr", "max"), "source"),""",
        """    "time_eater.haste": ("Buff", [("heal", ("expr", "max"), "source"),
                                  ("cleanse", "source"),""",
        'haste base cleanse')

# ④ collector.spawn：两个无条件 spawn → 三个被条件包住的 spawn（"up to 2"）
t = sub(t, """    "the_collector.spawn": ("Special", [("spawn", "torch_head", 38),""",
        """    # §329：wiki "Summons **up to 2** Torch Heads" —— 现在是"3 个敌人 ⇒ 0 只 / 2 个 ⇒ 1 只 /
    # 否则 2 只"的三层条件，所以事实里三条 `spawn` 各自挂着一个 `when`（事实模型不表达计数，
    # 计数语义由 `the_collector_summons_only_up_to_two_torch_heads` 那条**行为**判据钉住）。
    "the_collector.spawn": ("Special", [("when", None, "when", None, "spawn", "torch_head", 38),
                                        ("when", None, "when", None, "spawn", "torch_head", 38),
                                        ("when", None, "when", None, "spawn", "torch_head", 38)]),""",
        'collector spawn')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('inventory synced')
