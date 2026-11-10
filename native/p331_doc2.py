"""§331 文档数字（N'loth 让事件变成 36 条 / 三幕池 39 条，Act 2 到 13/13）。"""

import io

README = 'README.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


r = io.open(README, encoding='utf-8').read()
r = sub(r, "**35 个事件**（三幕池 13+15+10 = 38 条，跨幕复用 3 条；110 个 `EVND` 段）",
        "**36 个事件**（三幕池 13+16+10 = 39 条，跨幕复用 3 条；111 个 `EVND` 段）",
        'readme content row')
r = sub(r, """* **事件**：**35 条**（三幕池 13+15+10 = 38 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用，110 个 `EVND` 段）。""",
        """* **事件**：**36 条**（三幕池 13+16+10 = 39 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用，111 个 `EVND` 段）。""",
        'readme events count')
r = sub(r, """  **与 wiki 的 31 条相比是 28 条**：Act 1 **11/11**、Act 2 **12/13**、Act 3 **7/7** ——
  唯一明确不做的是 `cursed_tome`（`necronomicon` 不在范围）。**仍缺**：事件级条件
  （"这条事件出不出现"）与"从手上任选一件遗物失去"（`N'loth`）。逐条见 `docs/event-gaps.md`。""",
        """  **与 wiki 的 31 条相比是 29 条**：Act 1 **11/11**、Act 2 **13/13**、Act 3 **7/7** ——
  唯一明确不做的是 `cursed_tome`（`necronomicon` 不在范围）。**事件级条件**（"这条事件出不出
  现"）与 `N'loth` 的两件**随机候选遗物**都已做（§331）。逐条见 `docs/event-gaps.md`。""",
        'readme events tail')
io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
print('README numbers')

g = io.open(GAPS, encoding='utf-8').read()
g = sub(g, """enemy actions 166 / relics 152 / potions 33 / events 38 (13+15+10) / start deck 10""",
        """enemy actions 166 / relics 152 / potions 33 / events 39 (13+16+10) / start deck 10""",
        'gap pastable')
g = sub(g, """`38` 是三个幕的事件池之和（`13+15+10`），**不是**不同事件数 ——""",
        """`39` 是三个幕的事件池之和（`13+16+10`），**不是**不同事件数 ——""",
        'gap pastable note 1')
g = sub(g, """去重之后是 **35 条**
> （§318–§325 把 Act 1/2/3 补到 11/12/7，与 wiki 的 31 条比是 **28 条**，只差 `cursed_tome`）。""",
        """去重之后是 **36 条**
> （§318–§325 把 Act 1/2/3 补到 11/12/7，§331 又补了 `nloth` ⇒ Act 2 到 **13/13**，
> 与 wiki 的 31 条比是 **29 条**，只差 `cursed_tome`）。""",
        'gap pastable note 2')
g = sub(g, """| 事件 | **35 条**（三幕池 13+15+10 = 38 条，110 个 `EVND` 段）""",
        """| 事件 | **36 条**（三幕池 13+16+10 = 39 条，111 个 `EVND` 段）""",
        'gap D events')
g = sub(g, """与 wiki 的 31 条比是 **28 条**（Act 1 11/11、Act 2 12/13、Act 3 7/7）""",
        """与 wiki 的 31 条比是 **29 条**（Act 1 11/11、Act 2 13/13、Act 3 7/7）""",
        'gap D events tail')
g = sub(g, """| 内容（`cursed_tome` 明确不做 —— `necronomicon` 不在范围）。机制侧仍缺**事件级条件**与"任选一件遗物失去"（`N'loth`），见 §2 与 `docs/event-gaps.md` |""",
        """| 内容（`cursed_tome` 明确不做 —— `necronomicon` 不在范围）。机制侧的事件级条件与 `N'loth` 已做（§331） |""",
        'gap D events need')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g)
print('gap numbers')
