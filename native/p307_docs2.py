"""§307 文档核对（二）：`docs/mechanism-gaps-analysis.md`。

这份文档是 §277 的**分析记录**，两个缺口后来都落地了（§278/§279/§280/§281），
但正文里还留着三处会让接手的人读错的字句：

1. 开头没有"现状" —— 读者会以为两个缺口还在等；
2. "✅ 状态：方案 A 已落地…**方案 B（条件选项）仍未做**" 与后面 "✅ 状态：方案 B 已落地" **自相矛盾**；
3. 缺口二的开头还写着"没有 `randomInt` 这一类"（现状陈述），而它早就有了。

做法：加现状块（一句话 + 表格 + 指向），把三处改成"当时 / 现在"的对照，其余分析原文保留
（它记录的是"为什么这么加"，有历史价值）。
"""
import io

PATH = 'D:/Vibe/sts-tui/docs/mechanism-gaps-analysis.md'

STATUS = '''# 两个机制缺口：分析记录（§277）与**关闭状态**（§306 核对）

> ## 现状（先读这一段）
>
> **两个缺口都已经关闭**。本文保留的是 §277 的分析原文，它记录"为什么这么加" ——
> 其中两条结论后来被证明是**误判**（正文里逐条标了"检查之后是错的"）。
>
> | 缺口 | 关闭于 | 落成了什么 |
> |---|---|---|
> | 事件剧情分支被合并 | §278（`EVND` 段表）+ §279/§280（`Requires` / `relic_lose` / `gold_cost` / 小数百分比）+ §290/§300（`gold_all` / `card:<id>`） | 选项数不固定的节点表 + 闭词表条件；`dead_adventurer` 那棵 **25 屏**的树是真内容 |
> | 战斗中的随机没有值节点 | §281 | `expr::randomInt{Min,Max}` + `CombatState::draw_in_range`（**唯一入口**：`random_step` 推进、`seed` 不动）；当时担心的"预检也求值"是误判 |
>
> **现在真正的机制缺口**（不是这两条）记在 `docs/event-gaps.md` §3：
> ① 事件级条件还没盖全（`MinFloor` / `MaxFloor` / `MinGold` **已有**，缺遗物 / HP% / 计时）；
> ② "任选一件遗物失去"的问句（`N'loth`）；③ `remove_all:<id>` / `dup_deck` / `upgrade_all`。
>
> 下面从"## 缺口一"开始是**原文**。

---

'''

OLD_HEAD = '''# 两个机制缺口的重构方案（§277 分析）

> 读者：**接手下一批的人**。这两条不是"还没做的内容"，而是**内核/内容表达不了**的规则，
> 所以它们挡住的是一整类实体（事件的剧情分支、战斗中每回合重掷的随机）。
> 本文只写"缺什么载体、怎么加、加完怎么证明"，不含实现。
>
> 出处：`docs/port-plan.md` §277；两个缺口的现状记在 `docs/sts-wiki-gap.md` §C / §D。
'''

# ① 自相矛盾的那一句 —— 改成"当时 / 现在"
OLD_CONTRADICTION = '''`EVND` 段 + `EV.Entry` 已经做了，11 个旧事件机械迁移（语义快照逐字段比对），
`golden_idol` 补成真树（两段 + 三选一）。**方案 B（条件选项）仍未做** —— 见下面的清单。
下面保留当时的分析原文，作为"为什么这么加"的记录。'''
NEW_CONTRADICTION = '''`EVND` 段 + `EV.Entry` 已经做了，11 个旧事件机械迁移（语义快照逐字段比对），
`golden_idol` 补成真树（两段 + 三选一）。

⚠️ 这一段原文接着写"**方案 B（条件选项）仍未做**" —— 那是**写 §278 时**的状态；
§279/§280 之后方案 B 也落地了（见本节更上面的 ✅ 状态）。留在这里是因为下面的改动清单
仍然是"要做 B 时照着做"的备忘录。
下面保留当时的分析原文，作为"为什么这么加"的记录。'''

# ② 缺口二开头的现状陈述
OLD_GAP2 = '''### 现状（可查的事实）

`ir.rs` 的 41 个节点里**没有** `randomInt` / `randomChoice` 这一类。随机只存在于三处：'''
NEW_GAP2 = '''### 现状（可查的事实）

> ⚠️ **这是 §277 当时的现状**。§281 之后 `ir.rs` 有 `expr::randomInt{Min,Max}`
> （**值节点**，不是程序节点），入口是 `CombatState::draw_in_range`。下面三段是历史记录。

`ir.rs` 的 41 个节点里**没有** `randomInt` / `randomChoice` 这一类。随机只存在于三处：'''


def main():
    s = io.open(PATH, encoding='utf-8').read()
    assert s.count(OLD_HEAD) == 1
    s = s.replace(OLD_HEAD, STATUS + '## 缺口一：**真实事件的剧情分支被合并**\n')

    # 去掉原文里紧跟着的"## 缺口一"标题（已经被上面那一行替代）
    s = s.replace('''## 缺口一：**真实事件的剧情分支被合并**

### 现状（可查的事实）''', '''### 现状（可查的事实）''', 1)

    assert s.count(OLD_CONTRADICTION) == 1
    s = s.replace(OLD_CONTRADICTION, NEW_CONTRADICTION)

    assert s.count(OLD_GAP2) == 1
    s = s.replace(OLD_GAP2, NEW_GAP2)

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(s)
    print('mechanism-gaps-analysis.md updated')


main()
