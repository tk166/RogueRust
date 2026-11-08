"""§299 文档：C 类三件（enchiridion / orange_pellets / dead_branch）+ 另外三件缺什么。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §299 C 类：三件纯内容程序，另外三件各缺一个原子

C 类的卖点是"**不动内核**"——规则全部写成内容的触发器 + 原子。这一节做了**三件**，
另外三件查清后确认**各缺一个原子**，一并记在下面（不假装做了）。

### 299.1 三件做掉了

| 遗物 | 触发器 | 程序要点 |
|---|---|---|
| `enchiridion` | `TurnStarted`（首回合计数器门） | `createRandomCardInstance{Tag: power, ToZone: Hand, CostZero: true}` |
| `orange_pellets` | `CardPlayed` | 三个计数器各按牌的种类 +1；三类齐 ⇒ +3 力量 / +3 敏捷，然后清零 |
| `dead_branch` | `CardExhausted` | `createRandomCardInstance{Tag: *, ToZone: Hand}` |

### 299.2 ★ `orange_pellets` 教的一件事：**计数器是请求，条件读的是当下**

第一版写成 `sequence[power, attack, skill, conditional(三类都 ≥1, 付钱)]`，结果**不付**。
诊断打印出计数器确实是 1/1/1，但第三张牌那一刻它**自己的**计数器还是 0 ——

> `setCombatantCounter` 与 `applyStatus` 一样是**入队请求**（排空时才落地），
> 而同一节目里的 `conditional` 求值的是**当下**的状态。

所以形状改成"**先 bump 自己，再用另外两个判断**"：

```
conditional(power  → sequence[bump(power),  conditional(attack≥1 且 skill≥1, 付钱)])
conditional(attack → sequence[bump(attack), conditional(power≥1  且 skill≥1, 付钱)])
conditional(skill  → sequence[bump(skill),  conditional(power≥1  且 attack≥1, 付钱)])
```

第三种类型出现在**这一张牌**上时，另外两个计数器已经在**前面几次排空**里落地了。
这条与 §294 的 `sundial`（读计数器 → 再自增）是同一个形状，但那次是**先读后写**，
这次必须**先写后用另外两个** —— 差别只在于"读的是不是自己那一个"。

### 299.3 `dead_branch` 需要内核的**一个小扩展**：通配 tag `*`

`createRandomCardInstance` 的池子按 tag 过滤（`in_random_pool`），而"任意牌"没有这样的
tag —— 一张牌要么 attack / skill / power，要么都不是。所以给 `in_random_pool` 加一条：
tag 是 `"*"` ⇒ **不过滤**（`+` 行与 `x_cost` 仍然排除，那两条是池子的**规矩**）。

⚠️ **已知偏差**：wiki 的 Dead Branch 是"**你的职业牌池**"里随机一张，而通配会带进
**无色牌**（本内容有 51 张）。内容没有 `ironclad` 这类 tag，而"不是 colorless"这种否定
语法内核不支持 —— 记在 F.19，不假装没发生。

### 299.4 ★ 负控逼出来的判据加强（第二次）

"池子只要 power"那条负控**第一版照样绿**：原判据只验"加了一张、不是 `+`、不是 X 费"，
把池子缩成一类它全满足。

加强时又踩第二个坑：**连抽 40 次却全是同一张** —— 因为每次新建 `arena()` 拿到的是
同一个 seed 与 `random_step`，抽签必然相同。改成**在同一场战斗里连抽 60 次**，
并要求 attack / skill / power **三类都出现过**。

⇒ 两条都是"判据看起来在测，其实没测"的同一族：**驱动形状**错了，断言再对也没用。

### 299.5 另外三件：各缺一个原子（明确记下）

| 遗物 | 缺什么 | 具体缺口 |
|---|---|---|
| `nilrys_codex` | `offerRandomCards` 的收尾**写死**成"进手牌且免费"（`ChoiceThen::ToHandFree`） | 需要该节点支持 `Then`（或一个新的 `offerRandomCardsToZone`） |
| `warped_tongs` | 没有"手牌里**随机**一张"的选择器 | `upgradeCards` 按牌区顺序取前 N 张；`sel.random` 只对**战斗员**，不对牌 |
| `mummified_hand` | 没有内容原子写 `standard.card_cost_override` | 只有 `createRandomCardInstance{CostZero}` 与内核的 `playTopCardOfDrawPile` 会写它 |

### 299.6 判据与负控

| 判据 | 钉住 |
|---|---|
| `enchiridion_adds_a_free_power_card_on_the_first_turn` | 手牌 +1、那张是 **Power**、带 `card_cost_override = 0`；不带遗物时手牌不变 |
| `dead_branch_adds_a_random_base_card_when_a_card_is_exhausted` | 逐次 +1 张、基础牌、非 X 费；**60 次连抽覆盖三类** |
| `orange_pellets_pays_once_all_three_card_kinds_were_played` | 两类不付 / 三类 +3+3 / 第四张不重复付 |

**负控 3 条全红**（都改内容再重编）：`CostZero → false` / 池子 tag `* → power` /
`orange_pellets` 只看两个计数器。

### 299.7 账

内容遗物 **140 → 143**（缺 53 → 50）；状态 **139 → 142**；镜像 **166,584 B**；
`rd-core` **806**（+3）/ `rd-run` 181 / `rd-wasm` 143；矩阵 865 行；八道页面门 + `SOAK`；21/21。

### 299.8 剩下的（`docs/sts-wiki-gap.md` F.19）

* 上面三件的原子（`offerRandomCards.Then` / 随机手牌选择器 / 写 `card_cost_override` 的原子）；
* **E 类**（地图/页面）：`wing_boots`、`frozen_eye`；
* **F 类**：`strange_spoon`（消耗改丢弃 50%）；
* **G 类**：`neows_lament`（开局三场敌人 1 血）；
* **H 类**：`gambling_chip` / `toolbox`（开战前三选一）；
* **不做**：`necronomicon`（打两次）、无色池相关的 `prismatic_shard` / `toolbox` 部分、
  另外三个角色的专属遗物、Blight。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§299 C 类' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''### F.18 遗物：治疗与放行（§298）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.19 遗物：C 类纯内容程序（§299）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `enchiridion` | 开战加一张随机 Power 牌、这次免费 | **已做**（纯内容） | 一致 |
| `orange_pellets` | 一回合内 Power+Attack+Skill ⇒ +3 力量/敏捷 | **已做**（纯内容，三个计数器） | 一致（Focus 属 Defect，本角色没有 ⇒ 只给力量+敏捷） |
| `dead_branch` | 每消耗一张牌 ⇒ 手牌加一张随机牌 | **已做**（新增通配 tag `*`） | **偏差**：池子是"任意基础牌"（含无色），wiki 是"你的职业牌池" |
| `nilrys_codex` | 回合末三选一塞进抽牌堆 | **没做**：`offerRandomCards` 的收尾写死 `ToHandFree` | 缺原子 |
| `warped_tongs` | 回合初随机升级手牌一张 | **没做**：没有"手牌里随机一张"的选择器 | 缺原子 |
| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **没做**：没有内容原子写 `card_cost_override` | 缺原子 |

### F.18 遗物：治疗与放行（§298）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§298）', '（主计划 §1–§299）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
