"""§217 part 4: the deviation column stops reporting history as if it were a deviation.

`gap §G` has two tables: "已修" (history: old value -> new value) and "仍然故意不修" (a live
deviation). §215 parsed **both**, so eight fixed moves (`spiker.cut`, `chosen.poke`, ...) were
listed as current deviations -- "ours 8 / wiki 7" reads like a live gap, but §191 fixed it.

Now only the "故意不修" / "放宽" tables are parsed, and `standard.slow`'s real deviation (we gate on
"Direct damage", the wiki says "damage from Attack cards") gets its own machine-readable row.
"""
import io

G = 'docs/sts-wiki-gap.md'
P = 'native/coverage_matrix.py'

# ── 1) gap 文档：把 §216 那段散文变成一行可解析的偏差 ─────────────────────────────────────────
gap = io.open(G, encoding='utf-8').read()
old = '''§216 起 **`Slow` 有一处写明了的偏差**：wiki 说它只放大"**打出攻击牌造成的伤害**"，而我们的修饰器
只有"直接伤害"这一道门（`RestrictDamageKind: Direct`）—— 药水之类的非卡牌直伤也会被放大。
要精确到"攻击牌"需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对非空值**响亮拒绝**），
留作格式升级的工作。基线行为（本回合牌数、每回合归零、不复合）已与 wiki 一致。'''
new = '''### G.2 语义放宽：只放大"谁"的伤害（不是数值偏差）

| 实体 | 我们 | wiki | 为什么留着 |
|---|---|---|---|
| `standard.slow` | 放大**任何直接伤害**（`RestrictDamageKind: Direct`） | 只放大"**打出攻击牌**造成的伤害" | 要精确到卡牌标签需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对非空值**响亮拒绝**），留作格式升级。基线（本回合牌数、每回合归零、不复合）已与 wiki 一致（§216） |'''
assert gap.count(old) == 1
io.open(G, 'w', encoding='utf-8', newline='\n').write(gap.replace(old, new))
print('gap doc: §G.2 table added')

# ── 2) 解析器：只认"故意不修"与"放宽"那两张表 ───────────────────────────────────────────────
text = io.open(P, encoding='utf-8').read()
old = '''    in_g = in_h = False
    for line in lines:
        if line.startswith('### G.'):
            in_g, in_h = True, False
            continue
        if line.startswith('## H.'):
            in_g, in_h = False, True
            continue
        if line.startswith('### ') or line.startswith('## '):
            in_g = in_h = False'''
new = '''    in_g = in_h = False
    armed = False          # §217：只在"仍然故意不修" / "放宽"那两张表下解析
    for line in lines:
        if line.startswith('### G.'):
            in_g, in_h = True, False
            # §217：§G 有**两张**表 —— "已修"（历史：原值 → 现在）与"仍然故意不修"（现存偏差）。
            # §215 把两张都解析了，于是 8 条早已修好的招式（`spiker.cut`、`chosen.poke` …）
            # 在矩阵里被列成"现存偏差"，读起来像"ours 8 / wiki 7"。只认后一张。
            armed = ('不修' in line) or ('放宽' in line)
            continue
        if line.startswith('## H.'):
            in_g, in_h = False, True
            armed = False
            continue
        if line.startswith('### ') or line.startswith('## '):
            in_g = in_h = armed = False
        if not armed and in_g:
            # "仍然**故意不修**"这句在表格**之前**，是那一表的开关。
            if '故意不修' in line:
                armed = True
            continue'''
assert text.count(old) == 1
text = text.replace(old, new)
io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('parser: only the live-deviation tables')
