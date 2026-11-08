"""§295 文档：A2 `BlockBroken` 触发器 + `hand_drill`。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §295 A2：`BlockBroken` —— 一个事件，两个槽

`hand_drill`: *"Whenever you break an enemy's Block, apply 2 Vulnerable."*
一句话里有两件事，必须落在两个**不同的槽**上：

| 槽 | 谁 | 为什么 |
|---|---|---|
| **Bearer**（谁的遗物在听） | **打破格挡的人**（出手方） | wiki 说的是 "**you** break" |
| **EventTarget**（`sel.eventTarget`） | **格挡被打穿的那一方** | "apply 2 Vulnerable" 落在**它**身上 |

这与 `DamageDealt` 是同一方向（出手方 → 承受方），所以不新造一种"事件方向"。

### 295.1 ★ 这个槽最容易写错，而且错了**看起来是对的**

内容里把目标选择器写成 `sel.source`（而不是 `sel.eventTarget`）时：触发器照触发、
状态照施加、没有报错 —— 只是**易伤落在了英雄自己身上**。这正是 §4.20 的近亲：
"同一个词表被两处认识就一定漂"，而这里是"两个槽同形，选错一个不报错"。

所以负控第 ④ 条专门改**内容**（把目标槽换成 `sel.source`）并要求判据红，
判据里也有一条**反向**断言（`vulnerable(&state, &hero) == 0`）—— 只验"敌人有 2 层"
是不够的，因为"敌人和英雄各 2 层"也满足它。

### 295.2 "打破"的定义（三条同时成立，每条都有反例）

```
!ignores_block         // 毒 / Constricted 根本没碰格挡
&& block_before > 0    // 否则"格挡 0 打掉 0" = 每次攻击都加易伤
&& blocked == block_before   // 整池格挡全被这一次吃掉
&& source != target    // "an enemy's Block"：自己打自己不算
```

落点在 `resolve_damage` 的 S4（防御池吸收）之后、S5（扣血）之前 —— 那里是"格挡发生了多少"
唯一的真相点。`block_before` 在 S4 之前把池子求和记下来（原来没有这个数）。

事件**入队**，由回合机的事件循环解析（与 `BlockGained` / `CardsDrawn` 同一条路）。

### 295.3 新增一条派发路径 `run_triggers_with_target`

`run_triggers` 不设 `EventTarget`，`run_downed_triggers` 内联了自己的循环（因为它之后还要派
`FoeDowned`）。这条事件只需要"Bearer + EventTarget"，所以走一条通用路径。

⚠️ **没有**把 `EventTarget` 加进 `run_triggers` 当参数：那会改 25 处调用点，其中 24 处传
`None` —— "绝大多数传同一个值"的参数是签名在说谎。

### 295.4 判据（一条，四段）

`breaking_a_block_applies_vulnerable_on_the_target_only`（`host.rs`，真镜像 + 真事件循环）：
残血 3 格挡打 2 点**不**触发 / 1 格挡打 2 点触发（**敌** 2 层、**英雄** 0 层、血量只掉 1 ——
顺带钉住"格挡真的吸收了"）/ 自己打自己**不**触发 / 状态不在身上时什么都不发生。

### 295.5 负控 4 条（全红）

不看"原本有格挡" / 不看"打穿了" / 不看 `source != target` / **内容里目标槽写成 `sel.source`**。

### 295.6 账

内容遗物 **132 → 133**（缺 61 → 60）；状态 **131 → 132**；镜像 **163,860 B**；
`rd-core` **798**（+1）/ `rd-run` 181 / `rd-wasm` 141；矩阵 845 行；八道页面门 + `SOAK`；21/21。

### 295.7 A 项剩下的

| 缺的事实 | 遗物 | 说明 |
|---|---|---|
| "打出的牌带某 tag 时伤害 +N" | `strike_dummy` | 伤害管线第四个改写点（§263 已开过三个） |
| X 费牌的 X 加数 | `chemical_x` | 最小：`x_cost` 已经是 `PlayPlan` 的字段 |
| 隐藏敌人意图 | `runic_dome` | 运行层标记 → 观测 → 页面 |
| 每回合出牌上限 | `velvet_choker` | `plan_play` 的拒绝 + 一个计数器 |
| 战斗中治疗倍率 | `magic_flower` | `heal` 的数值改写 |
| `unplayable` 放行 | `medical_kit` / `blue_candle` | `validate_card_play` 的例外 |
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§295 A2：`BlockBroken`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    prefix = "| 中资产 | ~30 | 缺一个**事实/事件** |"
    for line in g.split(chr(10)):
        if line.startswith(prefix) and "hand_drill" in line:
            g = g.replace(line, "| 中资产 | ~30 | 缺一个**事实/事件** | `tough_bandages` `tingsha`（缺 `CardDiscarded`）、`bottled_*`（拾取时绑牌）、`gambling_chip`（§293–§295 之后的余项） |")

    marker2 = '''### F.14 遗物：洗牌触发器（§294）'''
    assert g.count(marker2) == 1
    g = g.replace(marker2, '''### F.15 遗物：打穿格挡（§295）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `hand_drill` | 打穿敌人的格挡 ⇒ 2 层易伤 | **已做**（`BlockBroken` + 内容 `applyStatus`） | 一致 |
| "打破"的口径 | 整池格挡被这次伤害打空 | 三条同时成立（原本有 / 打空 / 不是自己） | 一致 |
| 易伤落在谁身上 | 被打破格挡的那一方 | `sel.eventTarget`（判据反向断言英雄 0 层） | 一致 |

### F.14 遗物：洗牌触发器（§294）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§294）', '（主计划 §1–§295）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
