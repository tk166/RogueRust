"""Rewrite §161.8's Boss section: it is no longer a gap.

The honest first version reported `REACHED=false` and printed the trail. The next commit made it
reach and beat the boss, so the section must say what is true now -- and keep the trail of *why* it
was hard, because that is the part worth remembering.
"""
import io

PATH = "docs/port-plan.md"

OLD_START = "#### 五条场景让四种节点变成断言，Boss **如实报未达成**"
OLD_END = "#### 切片**照出**的四个真 bug（这才是它存在的理由）"

NEW = """#### 五条场景，五种节点，全部进断言

Boss 是**地图之外的哨兵游标**（`inv:§7.2`：第 16 层，不在 15 行里），所以"走到幕末" = 走到最后一行、
结算那个篝火、让游标落到哨兵上。现在**整幕都能走通**，而且是带着 90/90 血走到的：

```text
boss   seed=101 ms=1370 kind=7 floor=16 actBefore=1 actAfter=2 hpAfter=90 maxHp=90
       potionOpened=1 potionSource=2 potionOptions=3 potionAnswered=true won=true mapNodes=65
```

`actAfter=2` + `hpAfter == maxHp` + `mapNodes=65` 三件事合起来才是"幕末"：幕推进了、按 A0 的规则回满、
下一幕有图。另外 `potionSource=2 / potionOptions=3` 是 §161.7 那个**锚点**：在 Boss 战里喝一瓶
Attack Potion，它开出三张候选的选牌问句，驱动器回答它、打出那张免费牌。

第一版**没有**这么写。它当时停在第 12 层一个三只 Sentry 的精英上（`REACHED=false` + trail），
而把它改成 `want` 的两种做法都是撒谎：闸门因为驱动器 bug 常红，或者悄悄跳过。所以那时它只打印
证据。**接下来那次提交把它做通了**，这一节才是现在这段话。留下这段是因为"先如实报未达成"本身
是这套闸门的一部分，不是一段过渡期的耻辱。

#### 做通 Boss 需要三件事，每件都是一个真问题

1. **两条"选敌人"的通道不能混**（这是 25 分钟 stall 的真因）。页面里
   `data-enemy-panel` 在**每个**敌人面板上都有，而 `data-target-slot` **只在被武装的牌能打到的**
   那几个上有；点击处理器在"有牌被武装"时只认后者、否则直接 return。驱动器原来把前者放在 `||`
   左边 —— 于是"武装一张牌、点一个不可及的面板、什么都没发生、而那张牌还武装着" ⇒ **后续每一次
   点牌都被忽略**。现场证据是 `acts11/cards5/endon/energy3` 全正常，只有 `armY`/无进展。
2. **策略得能赢一整幕**。第一版"有攻击牌就攻击、从不格挡"在 50/95 血进 Boss 战然后输掉。
   改成：**只有这一击会致死才格挡**（"来 27 点、格挡 5 点"时格挡只是让战斗更长），其余全力打，
   并且**打血最少的那个敌人**（少一个敌人就少一份 incoming）。药水在**半血**时喝。
   ⇒ 同样的种子，改完之后带着 **90/90** 走到 Boss。
3. **路线要能避开精英**。"最短"和"最安全"是两个问题：第一版 BFS 求最短，于是笔直穿过三只 Sentry
   的精英（hp 5 活着出来，第 11 层死掉）。改成按**代价**寻路（精英 50、其它 1）——
   一个拿着起始牌组的玩家就是绕开精英走的，而分支地图存在的理由正是这个。

#### 还有两个"两个副本漂了"的地方

* **"再来一局"与"再打一局"**：`ui_panels.js` 把同一个按钮拼了两种写法，而驱动器的"不许点重开"
  守卫只写了其中一种 ⇒ 死掉之后驱动器**重启了整局**，于是 trail 里出现三次完整的行走、
  却没有任何一处说"死了"。守卫现在写成 `/再[打来]一局/`。
* **观察向量的"金币"**：运行层是 **index 4**，`5` 是**牌组张数**。驱动器把 5 当金币，
  于是"买卡没扣钱"其实是"牌组变长了"—— 一个看起来完全合理的错，而且断言写法也是错的
  （它比较的是两个牌组长度）。

"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(OLD_START)
    end = text.index(OLD_END)
    text = text[:start] + NEW + text[end:]

    # the numbers paragraph and the todo list
    old_digits = """- 新闸门 `web-slice`：4 条场景（商店 / 事件 / 篝火 / 精英）全绿，Boss 如实报未达成。
  场景耗时：商店 0.6 s、事件 0.3 s、篝火 0.6 s、精英 1.0 s、Boss 25 s（走到 f12）。"""
    new_digits = """- 新闸门 `web-slice`：**5 条场景全绿**（商店 0.4 s / 事件 0.2 s / 篝火 0.5 s / 精英 0.7 s /
  Boss 1.4 s，合计约 3 s），Boss 那条从开局走到幕末、打完第 1 幕。"""
    assert text.count(old_digits) == 1
    text = text.replace(old_digits, new_digits)

    old_todo = """#### 还差的（下一节的第一件事）

- **Boss 场景**：fight 驱动器要在三敌战斗里走完"点牌 → 点目标"（页面有两条不同的选敌通道：
  打牌用 `[data-target-slot]`，药水用 `[data-enemy-panel]`）。
- 五条场景目前各自**只走到自己的节点**；"每条都从开局走到幕末"更贵，等 Boss 那条通了再合。"""
    new_todo = """#### 还差的

- 五条场景里只有 Boss 那条走到**幕末**；另外四条走到自己的节点就停（重走四遍一整幕只买运行时间，
  不买信息）。要"每条都从开局走到幕末"的话，代价是 5 × 1.4 s 加上更长的确定性预算。
- soak 仍然不认识选牌界面（它从不喝药水），覆盖率靠 `browser_test` 三段 + 这一道 5 条场景。"""
    assert text.count(old_todo) == 1
    text = text.replace(old_todo, new_todo)

    io.open(PATH, "wb").write(text.encode("utf-8"))
    print("§161.8 rewritten: the boss is green")


if __name__ == "__main__":
    main()
