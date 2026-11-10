"""§330 文档对账（第二半）：`docs/sts-wiki-gap.md`。

改的都是**过时陈述**，不动结构：

* §1 表格：状态 146→148、卡行 293→295、Ascension 98/85/53→128/107/59、遗物行；
* §1.1 pastable 区块 + 注释（去重事件 21→35、relics 152、变体 128/107、镜像字节）；
* §C：Boss 分裂那一行（相位已收口，分裂仍只有 Slime Boss）；
* §D：遭遇池（Act 2 13/13）、遗物（15 件→152/193）、篝火（六选项）、商店（无色 70/70）、
  事件（14 个→35 条 / 28 of 31）、Ascension（A17/18/19 已收口）；
* §H：Boss 的"剩余差异"逐条重写（§328–§330 关掉了绝大多数）；
* §3：建议顺序（篝火/精英/事件都已做完）；
* §4：补上新的两道闸门与 §330 的工具修复。
"""

import io

PATH = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── §1 表格 ───────────────────────────────────────────────────────────────────
t = sub(t, "| 状态 | **146 条**；每一条要么有内核规则",
        "| 状态 | **148 条**；每一条要么有内核规则", 'statuses')

t = sub(t, "| 卡牌（**数量**） | **293 行 = 154 张基础 + 139 条升级行**；",
        "| 卡牌（**数量**） | **295 行 = 155 张基础 + 140 条升级行**；", 'cards')

t = sub(t, """数值侧：**98 条变体 / 85 个动作**（**53 个动作仍无 wiki 出处**，`audit_asc_gap.py` 打印）+ 事件列表的 A15 变体。逐条见 §E | §159 / §187–§192 / §306 核对、`gap_check.py` |""",
        """数值侧：**128 条变体 / 107 个动作**（**59 个动作仍无 wiki 出处**，`gap_check.py` 打印 `without a variant: 59`）+ 事件列表的 A15 变体。⚠️ §328 起有**闸门**：wiki 写了 `{{Asc|N|` 而内容缺档的动作必须是 **0** 条（`sts_content_check.py` 的 `[7b]`）；人跑的对账是 `audit_asc_gap.py`（§330 修好了它只读第一个档位的解析 bug）。逐条见 §E | §159 / §187–§192 / §306 / §328–§330 |""",
        'ascension row')

# ── §1.1 pastable 区块 ────────────────────────────────────────────────────────
t = sub(t, """```
monsters 61 / encounters 64 / cards 295 (base 155 + plus 140) / statuses 148 /
enemy actions 166 / relics 153 / potions 33 / events 38 (13+15+10) / start deck 10
ascension variants 117 over 101 actions
image full   content.sts.rdcf            179288 B
image core   content.sts.core.rdcf       142344 B
```""",
        """```
monsters 61 / encounters 64 / cards 295 (base 155 + plus 140) / statuses 148 /
enemy actions 166 / relics 152 / potions 33 / events 38 (13+15+10) / start deck 10
ascension variants 128 over 107 actions
image full   content.sts.rdcf            189024 B
image core   content.sts.core.rdcf       151460 B
```""",
        'pastable block')

t = sub(t, """> ⚠️ **单位必须写清**（审阅 §8 第 5 条）：`117` 是**卡行**（61 基础 + 56 升级行），不是 117 张不同的牌
> —— 而且其中包含状态/诅咒牌与多档升级行（`searing_blow+`…`++++++`）；
> `117 / 101` 是**变体 / 动作**；`38` 是三个幕的事件池之和（`13+15+10`），**不是**不同事件数 ——
> `golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用，去重之后是 **21 条**（§F.25）。
> `relics 152` 是**内容行**；wiki 有 193 条，缺 41 条（§D.2）。""",
        """> ⚠️ **单位必须写清**（审阅 §8 第 5 条）：`295` 是**卡行**（155 基础 + 140 升级行），不是 295 张不同的牌
> —— 而且其中包含状态/诅咒牌与多档升级行（`searing_blow+`…`++++++`）；
> `128 / 107` 是**变体 / 动作**；`38` 是三个幕的事件池之和（`13+15+10`），**不是**不同事件数 ——
> `golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用，去重之后是 **35 条**
> （§318–§325 把 Act 1/2/3 补到 11/12/7，与 wiki 的 31 条比是 **28 条**，只差 `cursed_tome`）。
> `relics 152` 是**内容行**（§330 之前这里是 153 —— 那多出来的一行是 `mutagenic_strength`
> 的**重复行**，现在有闸门 `[7g]` 挡着）；wiki 有 193 条，缺 41 条（§D.2）。""",
        'pastable note')

# ── §C 战斗流程：Boss 分裂那一行 ──────────────────────────────────────────────
t = sub(t, """| Boss 分裂 | **有**，但目前**只有 Slime Boss**（`destroyCombatant` 到位后，"消失 + 两只顶替"才第一次能正确表达，§178） | 内容（另两只 Boss 各有新东西） |""",
        """| Boss 分裂 | **有**，但目前**只有 Slime Boss**（`destroyCombatant` 到位后，"消失 + 两只顶替"才第一次能正确表达，§178）。⚠️ "相位"是另一件事，六个 Boss 的相位规则已在 §329–§330 逐条对过 wiki | 内容（另两只 Boss 各有新东西） |""",
        'boss split row')

# ── §D 运行层：五处过时行 ─────────────────────────────────────────────────────
t = sub(t, """| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量） | 内容（第二幕的普通池只有 2 个） |""",
        """| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量）：普通池 Act 1 **17** / Act 2 **13/13** / Act 3 **10/10** | — |""",
        'encounter pool row')

t = sub(t, """| 遗物 | **15 件**（9 Common / 4 Uncommon / 1 Rare / 1 Event，`gap_check.py` 打印）。效果是 `rd-run` 里的**手写规则**，不是数据 | 内容 + 内核（每件一条规则）。⚠️ 总数**仍未核对**（wiki 的 `Relics List` 是模板生成的；`Relics` 的 Cargo 表可以像卡表那样查，但还没做 —— 下一轮补 `audit_relic_gap.py`） |""",
        """| 遗物 | **152 / 193**（`audit_relic_gap.py` 的账：`MISSING: 41`、`METADATA: 0`、`IMPLEMENTED: 内核不认识 0`）。分档、载体决策树与逐条清单见 §D.2 与 `docs/relic-inventory.md` | 内容（缺的 41 件：Blight 13 / 别的角色 20 / `bottled_*` 3 / `necronomicon` / `circlet` 2 / 其余 2） |""",
        'relic row')

t = sub(t, """| 篝火选项 | **只有 Rest / Smith**。wiki 的 `Rest Sites` 页有三组：① 标准 = Rest（30%，`Coffee Dripper`/`Mark of the Bloom` 灰掉，满血也可用）/ Smith（`Fusion Hammer` 或全升完则灰）/ **Recall**（拿 Ruby Key，只在 Act 4 已解锁且本幕没拿过时出现）；② 遗物开启 = `Girya`→**Lift**（每次 +1 力量、最多 3 次，之后**每场战斗开始**都带这些力量）/ `Peace Pipe`→**Toke**（删一张）/ `Shovel`→**Dig**（随机遗物，只要 Common/Uncommon/Rare）；③ 被动 = `Regal Pillow`（休息 +15，**已有**）/ `Eternal Feather`（进篝火按牌数回血，**已有**）/ `Dream Catcher`（休息后给一张卡奖励，**没有**） | 内核（新选项类型 + "每场战斗开始加力量"的跨层传递）+ 内容（`girya` / `peace_pipe` / `shovel` / `coffee_dripper` / `fusion_hammer` / `dream_catcher` 六件遗物） |""",
        """| 篝火选项 | **六个全通**（§259）：Rest / Smith / **Recall**（红钥匙）/ **Lift**（`Girya`，最多 3 次、之后每场战斗带这些力量）/ **Toke**（`Peace Pipe`，删牌免费）/ **Dig**（`Shovel`，只抽 Common/Uncommon/Rare）；`Coffee Dripper` / `Mark of the Bloom` 关 Rest、`Fusion Hammer` 关 Smith、`Dream Catcher` 让休息额外给一次卡牌奖励 | — （`Recall` 的用处是第四幕，见最后一行） |""",
        'campfire row')

t = sub(t, """| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价）。⚠️ **无色牌不出售**：没有 StS 的无色货架，无色牌的唯一来源是 Colorless Potion（§185）。**且内容里只有 3 张 `colorless` tag 的牌**（`audit_card_gap.py` 说 Colorless 桶 14/70） | 内核（无色货架：`stock_shop` 再加一排）+ 内容（31 张商店三档无色牌，见 §A.1） |""",
        """| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价；`the_courier` 刷新货架、`membership_card` 打折）。⚠️ **无色牌仍不出售**：没有 StS 的无色货架 —— 内容侧的无色池已经 **70/70**（§243–§252），缺的只是**商店里那一排**（`stock_shop` 加一排即可） | 内核（无色货架） |""",
        'shop row')

t = sub(t, """| 事件 | **14 个**（三幕 6+4+4，`gap_check.py` 打印），每个选项是**一串**效果（§188），从 A15 起换用 `Effects*Asc` 的糟版本。词表仍是闭集：`heal / gold / damage / max_hp / nothing / remove_card / upgrade_card / transform_card / curse:<id> / relic:<id>` | 内容（缺真实事件的剧情分支：Golden Idol 的 Outrun/Smash/Hide 三选一在我们这里压成两选项，见 inventory §7） |""",
        """| 事件 | **35 条**（三幕池 13+15+10 = 38 条，110 个 `EVND` 段）。剧情分支是**真树**（`EVND` 段表 + `EV.Entry`，选项数不固定），选项支持 `Requires` / `RequiresAsc`、按类型的选牌问句（`the_library` / `sensory_stone` / `falling`）、事件中途开战斗（`dead_adventurer` / `mysterious_sphere` / `colosseum`）与 A15 的糟化分支。与 wiki 的 31 条比是 **28 条**（Act 1 11/11、Act 2 12/13、Act 3 7/7） | 内容（`cursed_tome` 明确不做 —— `necronomicon` 不在范围）。机制侧仍缺**事件级条件**与"任选一件遗物失去"（`N'loth`），见 §2 与 `docs/event-gaps.md` |""",
        'events row')

t = sub(t, """| **Ascension 1–20** | **20 / 20 条有机制**：14 条是运行层规则常量（A1 A5–A16 A20，`gap_check.py` 打印），A2/A3/A4 与 A17/18/19 走内容的 `EACT.ProgramAsc`。⚠️ A17/18/19 仍是**部分覆盖**（还有动作没有 wiki 出处），见 §E 与 §A.1 的说明 | 内容（补 17/18/19 的剩余动作） |""",
        """| **Ascension 1–20** | **20 / 20 条有机制**：14 条是运行层规则常量（A1 A5–A16 A20，`gap_check.py` 打印），A2/A3/A4 与 A17/18/19 走内容的 `EACT.ProgramAsc`。**wiki 写了 `{{Asc|N|` 而内容缺档的动作是 0 条**（闸门 `[7b]`，§328），档位按**怪物**钉（§315/§327） | — （`without a variant: 59` 是 wiki 本来就没写升档的动作） |""",
        'ascension row in D')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gap doc part 1 updated')
