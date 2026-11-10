"""§330：加一道"段内 id 不许重复"的闸门。

为什么现在加：审文档时发现内容里 `mutagenic_strength` **重复了一行**（`Relics` 153 行、
实际 152 条）。它从 §266 一直躺到 §329 —— 而 22 道闸门一条都没红：

* `sts_content_check.py` 的 `SEC_IDX` 检查只问"id 能不能索引到**一种**实体"，
  重复行照样索引得到；
* `audit_relic_gap.py` 用的是 `set`，重复自动被吃掉；
* 只有 `gap_check.py` 的 `relics 153` 与 audit 的 `152` 对不上时**才看得出来**，
  而那需要人把两个数字放在一起读。

"同一个 id 出现两次"在任何内容表里都只有坏处：一份被读、另一份静默作废，
而两份哪天改了不一样的东西就再也说不清哪份算数。
"""

import io

PATH = 'native/sts_content_check.py'

ANCHOR = """def check_ascension_variants(doc):"""

FUNC = '''# §330: 每个内容段的 `Id` 都必须唯一。
#
# 键是"段名 → 取 id 的方式"；值只用来打印。`Cards` 的 id 是裸串，`Monsters`/`Encounters`
# 是 `{"Value": …}`，所以两种形状都要认（这也是 §1.2 那条"两种 Id 形状"的延续）。
def check_unique_ids(doc):
    """§330: 同一个段里 `Id` 不许出现两次。"""
    import collections
    print("[7c] unique ids per section (port-plan.md §330)")

    def ident(row):
        raw = row.get("Id")
        if isinstance(raw, dict):
            return raw.get("Value")
        return raw

    sections = (
        ("Cards", doc.get("Cards")),
        ("Statuses", doc.get("Statuses")),
        ("Relics", doc.get("Relics")),
        ("Potions", doc.get("Potions")),
        ("EnemyActions", doc.get("EnemyActions")),
        ("Monsters", doc.get("Monsters")),
        ("Encounters", doc.get("Encounters")),
        ("EventNodes", doc.get("EventNodes")),
    )
    total = 0
    problems = 0
    for name, rows in sections:
        if not rows:
            continue
        counts = collections.Counter(ident(row) for row in rows)
        total += len(counts)
        for key, count in sorted(counts.items(), key=lambda kv: str(kv[0])):
            if count > 1:
                problems += 1
                fail("unique.%s" % name, "%r appears %d times" % (key, count))
    ok("unique ids", "%d ids over %d sections, %d duplicated"
       % (total, sum(1 for _name, rows in sections if rows), problems))


'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'def check_unique_ids' not in t, 'already patched'
t = t.replace(ANCHOR, FUNC + ANCHOR)
t = t.replace("""    check_wiki_asc_levels(doc)
    check_ascension_health(doc)""",
              """    check_wiki_asc_levels(doc)
    check_unique_ids(doc)
    check_ascension_health(doc)""", 1)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('checker: check_unique_ids added + wired')
