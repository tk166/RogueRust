"""§307 文档核对：四份文档的系统性复述（数字全部来自脚本输出）。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'

DOC = r"""
---

## §307 文档核对：四份文档与代码/wiki 的系统性对账

§306 之后停下来说明一件事：**代码在往前走，四份文档在往回漂**。
这一节逐份核对 `README.md` / `docs/sts-wiki-gap.md` / `docs/event-gaps.md` /
`docs/mechanism-gaps-analysis.md`，并把抓住的事实错误改掉。

### 307.1 先修了一个**内容**错误（审计脚本抓的）

`native/audit_relic_gap.py` 一直有一栏 `METADATA（两边都有但写错）`，这次它抓到 1 条：

```
toolbox   Rarity   ours='Rare' wiki='Shop'
```

是 §304 我按"看起来像 Rare"填的。改成 `Shop` 之后 `METADATA: 0`。
**这一栏之前是 0，所以它是"新引入的错误"** —— 说明这条审计对每一批新遗物都必须跑，
而它不在 21 道闸门里（`sts-content` 只查内容自洽，不查 wiki）。

### 307.2 抓住的过期数字（全部按脚本输出重写）

| 文档 | 旧说法 | 实际（脚本） |
|---|---|---|
| README §2 | 49 怪 / 43 遭遇 / 124 状态 / 130 敌人动作 / 115 遗物 / 14 事件 | **50 / 47 / 146 / 138 / 152 / 19**（池条目 22） |
| README §2 | 79 个动作有变体（91 个变体） | **85 个动作 / 98 条变体**（`audit_asc_gap.py`） |
| README §2 | 镜像 144,872 B / core 111,528 B | **168,008 B / 132,044 B**（`gap_check.py`） |
| README §5.2 | 标题"20 道闸门"、表 20 行 | **21 道**（`coverage-matrix` 是第 21 道，表里缺了它） |
| README §1.5 | `RD_DEBUG` 四行 | 补上 `giveRelic` / `startAnEvent`（§292/§293 就加了，文档没跟上） |
| gap §1.1 | pastable 区块（monsters 47 / cards 117 / statuses 46 / relics 15 / 镜像 92,644 B） | 整块重贴（50 / 293 / 146 / 152 / 168,008 B） |
| gap §D.2 | 遗物 115/193、桶表 5 行过期、**"缺的那 78 件"** | **152/193** + 桶表按 `MISSING` 分组重写 + **41 件** |
| gap §1 状态行 | "inert **18 条**" | **37 条**（`gap_check.py` 打印全名） |

### 307.3 抓住的**口径**错误（比数字错更值得记）

1. **"14 事件（三幕 6+4+4）"** —— 现在池子是 **10+8+4 = 22 条**，而**去重是 19 条**：
   `golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用。
   `gap_check.py` 打印的 `events 22 (10+8+4)` 是**池条目**，文档里必须写清这一点，
   否则下一次有人看到 22 会以为多了 3 个事件。
2. **"13 条事件已做"** —— 旧 `event-gaps.md` 的表里，`old_shrine` / `ancient_forge` /
   `purification_shrine` 是**我们自写的 shrine 类事件**，不在 wiki 的三幕清单里。
   按 wiki 的真实清单重算：**Act 1 = 8/11，Act 2 = 5/13，Act 3 = 1/7**。
   "13" 这个数字让人以为覆盖了 wiki 的 13 条。
3. **"事件级条件完全没做"** —— **错**。`EventTables` 的每一条可以带
   `MinFloor` / `MaxFloor` / `MinGold`，`rd-wasm` 在**掷骰之前先筛池**
   （`event_pool_at(floor, gold)`，§288/§291），用户是 `dead_adventurer`（≥7 层）、
   `the_colosseum`（≤7 层）、`the_joust`（>50 金币）。缺的是另外三类：遗物 / HP% / 计时。
4. **"两个机制缺口"** —— 都已关闭（§278–§281），而 `mechanism-gaps-analysis.md` 开头
   没有现状块、正文里还留着"方案 B 仍未做"与"`ir.rs` 没有 `randomInt` 这一类"两句话，
   与同一页后半的 ✅ 状态**自相矛盾**。现在开头有现状表，三处改成"当时 / 现在"的对照。

### 307.4 新增/重写的段落

| 文档 | 动作 |
|---|---|
| `docs/event-gaps.md` | **整体重写**：19 条事件逐条（选项数 / 条件选项 / 后续屏数）、wiki 三幕覆盖表、按"缺什么"分组（只缺内容 7 条 / 缺机制 9 条）、机制缺口 3 条（含"部分已有"的更正）、最近几轮的账、排序建议 |
| `docs/sts-wiki-gap.md` | §D.3 重写（三幕池子的**实际条数** + Act 2 普通池 3 vs wiki 13 是三幕里最大的敌人缺口 + 三条要新怪物）；§D.4 改成"两个已关闭"；新增 **§F.25**（§306 的 `runic_pyramid` 与 Ethereal 修正） |
| `docs/mechanism-gaps-analysis.md` | 加"现状（先读这一段）"表；三处矛盾改成对照；其余分析原文保留（它记录的是"为什么这么加"） |
| `README.md` | §2 的数字整段重写 + 遗物 41 件缺口的**分档拆解** + 事件改成"19 个 / 剧情分支已是真树" + 敌人补上 Act 2 普通池这条最大缺口；§5.2 补第 21 道闸门；§1.5 补两个 debug 入口；§3 的 `docs/` 行补两份文档 |

### 307.5 账

内容遗物 152（`toolbox` 的稀有度修正后镜像 **168,008 B 不变** —— 稀有度是 `REL` 行的一个
字节，长度没变、内容变了，所以 `contentc-bytes` 的 sha 变了）；
`rd-core` 809 / `rd-run` 185 / `rd-wasm` 151；矩阵 878 行 / tests 1147；
八道页面门 + `SOAK`；**21/21 闸门**。

### 307.6 这一节**没有**做的事（别当成已完成）

* 没有给"文档里的数字"加一道闸门。今天唯一会红的是 `coverage-matrix --check`（它只比对
  **它自己那份**生成物）与 `gap_check.py` 的 pastable 区块（**手工**贴，没人验）。
  ⇒ 一个便宜的做法：让 `gap_check.py` 直接**改写** `sts-wiki-gap.md` §1.1 那个代码块
  （现在它只打印），这样"陈旧的绿"就没有生存空间。
* 没有实现任何新机制/内容：`toolbox` 稀有度是**修正**，`runic_pyramid` 的 Ethereal 是 §306 的修正。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§307 文档核对' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)
    print('doc written')


main()
