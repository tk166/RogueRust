"""§330：`docs/sts-wiki-gap.md` §A.1 的"施工单"整段重写。

那段是 §246 时期写的（"红卡 75/75 齐；无色 38/70"），列着 30 多张"需要什么载体"的牌 ——
那些载体在 §247–§252 就全补上了（`ExhaustPile` 问句、`PlayCondition` 读整手牌、
"下一张 Attack 打两次"、随机生成/打出、问完再继续、读敌人意图……），无色现在是 **70/70**。
留着它有两个害处：数字自相矛盾（同一页上面写 70/70、下面写 14/70），而且会让人以为还得再做一遍。
"""

import io

PATH = 'docs/sts-wiki-gap.md'

START = """当前结果（`audit_card_gap.py --offline` 的输出，**数字照抄脚本**，别手写）："""
END = """> ⚠️ 同一张牌在我们的内容里也可能挂在别的颜色下（`malaise` / `nightmare` / `rip_and_tear` /
> `skewer` 是静默猎手牌、`blur` / `buffer` 是故障机器人牌，都在本内容里做过）。脚本把它们列成
> "content-only"，这是**有意的**：口径是"能玩的机制"，不是"只抄一个职业"。"""

NEW = """**现状（§252 之后没再变过）**：口径内 **147 / 220**，**缺的 73 张全是观者（紫）** ——
Red **75 / 75**、Colorless **70 / 70**、诅咒与状态齐。上面那段 pastable 区块里的
`cards 295 (base 155 + plus 140)` 是**卡行**，与这里的"张数"不是一个单位。

观者的 73 张不是"一张张补"能收的：它们成堆挂在**姿态系统**（`calm` / `wrath` / `divinity`，
约 30 张）、**Mantra / Divinity**、**Scry**、**Retain + `Establishment`**、
**`Alpha` → `Beta` → `Omega`** 上。所以下一批要按**基建**聚类做（先做姿态机与 Scry 两条载体，
再成批补牌），而不是照 §A.1 的清单从上往下写。

> ⚠️ **已删掉的一段**（§330）：这里原来是 §246 时期的"施工单"，按"需要什么载体"列了 30 多张
> 红卡与无色牌（`exhume` 要 `ExhaustPile` 问句、`clash` 要 `PlayCondition` 读整手牌、
> `double_tap` 要"下一张 Attack 打两次"、`havoc` / `infernal_blade` 要随机生成与强制打出、
> `burning_pact` 要"问完再继续"、`spot_weakness` 要读敌人意图……）。那些载体在 §247–§252
> 全部补齐了，无色也从 38/70 做到了 70/70 —— 留着那张单子会让人以为还得再做一遍，
> 而且它与同一页的"Colorless 70 / 70（齐）"直接矛盾。

> ⚠️ **口径**：只把 Red + Colorless + Curse + Status 算进范围；别的颜色只统计。S 同一张牌在我们
> 的内容里也可能挂在别的颜色下（`malaise` / `nightmare` / `rip_and_tear` / `skewer` 是静默猎手牌、
> `blur` / `buffer` 是故障机器人牌，都在本内容里做过）。脚本把它们列成 "content-only"，
> 这是**有意的**：口径是"能玩的机制"，不是"只抄一个职业"。"""

t = io.open(PATH, encoding='utf-8').read()
a = t.index(START)
b = t.index(END) + len(END)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t[:a] + NEW + t[b:])
print('A.1 rewritten')
