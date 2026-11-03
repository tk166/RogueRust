"""§194 docs: the plan section, plus the inventory / gap / README lines the boss pools moved."""
import io


def patch(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert src.count(old) == 1, "%s: %d x %r" % (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ---------------------------------------------------------------- inventory
patch("docs/spec/sts-act1-inventory.md", [(
"""> 仍然缺的是另外两只 Boss 的机制：Guardian 的 **Mode Shift**（受伤计数 + 形态状态机）、
> Hexaghost 的 **Burn 升级**。"三选一"这一层仍然无从体现 —— `Boss` 池只有 1 个。

> `inv:§4.3` 说三只等概率三选一【推断】；本内容只有一只，所以"三选一"这一层现在无从体现。""",
"""> ✅ **2026-11-03 第二次更新（§194）**：三只**都在**了，而且三幕的 Boss 池各自齐到 wiki 的
> "三选一"。降级是**写明**的（每条也在内容的 `AiNote` 里）：
>
> | Boss | 这一版怎么做的 | 与 wiki 的差 |
> |---|---|---|
> | The Guardian | 进攻 4 循环 + `Mode Shift` 用 **HP ≤ 50%** 触发一次，防御态 Roll Attack → Twin Slam → Whirlwind 后用计数器回到循环；**Sharp Hide 是精确的**（`CardPlayed` + `card.hasTag.attack`） | 触发条件是血量阈值而不是"累计受伤 30"，且切形态落在**下一轮**（意图每轮选一次） |
> | Hexaghost | 第 1/2 回合规则（Activate、Divider，Divider = `repeat(HP/12 + 1)`），之后 7 招循环**轮转对齐**；Sear 塞 Burn、Inferno 塞 Burn+ | Inferno 不升级已有的 Burn（没有"升级牌堆里的卡"节点）；Divider 读结算时的 HP |
>
> 第 2 / 3 幕的 Boss 同一次也对齐了 wiki（The Champ 420 HP 与四招、Time Eater 的 Haste、
> 以及四只新的：Bronze Automaton + 2 Orb、The Collector + 2 Torch Head、Awakened One 两阶段、
> Donu & Deca 一对）。细节见 `docs/port-plan.md` §194 与 `docs/sts-wiki-gap.md` §H。"""), (
"""### 5.5 Boss（1 只，等概率）""",
"""### 5.5 Boss（三只，等概率；§194 起三幕各三只）"""), (
"""| `enc_the_guardian` | The Guardian ×1 | 33.33% |
| `enc_hexaghost` | Hexaghost ×1 | 33.33% |
| `enc_slime_boss` | Slime Boss ×1 | 33.33% |""",
"""| `enc_the_guardian` | The Guardian ×1 | 33.33% |
| `enc_hexaghost` | Hexaghost ×1 | 33.33% |
| `enc_slime_boss` | Slime Boss ×1 | 33.33% |

第 2 / 3 幕（`Boss2` / `Boss3`）同样是三项等权：The Champ / Bronze Automaton（+2 Orb）/
The Collector（+2 Torch Head），Time Eater / Awakened One / Donu & Deca。

> ⚠️ **小兵是开局在场的**，不是召唤出来的：`intent::locate_enemy` 要靠遭遇名单给召唤物找招式表
> （§138），而列进名单就会生成 —— 所以 wiki 的 `Spawn Orbs` / `Spawn` 被去掉，两只 Orb 与两只
> Torch Head 从第 1 回合就站在场上。""")])

# ---------------------------------------------------------------- gap doc
patch("docs/sts-wiki-gap.md", [(
"""| 20 | 双 Boss（第三幕两只） | **有**（第一只倒下后节点重开，第二只才算赢，§189） | 内容：`Boss3` 池仍只有 1 个 —— 两场打的是同一只 |""",
"""| 20 | 双 Boss（第三幕两只） | **有**（第一只倒下后节点重开，第二只才算赢，§189） | §194 起 `Boss3` 池有 3 只，所以两场可以是不同的一对 |"""), (
"""`Boss3` 池仍只有 1 个，所以 A20 的两场打的是同一只 Boss。""",
"""§194 起 `Boss3` 池有 3 只，所以 A20 的两场可以抽到不同的一对 Boss。"""), (
"""| 2 | 普通敌人伤害提高 | **有**（`EACT.ProgramAsc`，内容覆盖 29 个动作；§193 起可变伤害也在这一档） | — |""",
"""| 2 | 普通敌人伤害提高 | **有**（`EACT.ProgramAsc`，内容覆盖 29 个动作；§193 起可变伤害也在这一档） | — |""")])

# ---------------------------------------------------------------- README
patch("README.md", [(
"""* **Boss**：每幕只有一只（Slime Boss / The Champ / Time Eater），而 wiki 是每幕三选一；
  Boss 分裂只有 Slime Boss 有（另外两只各要 Mode Shift / Burn 升级）。""",
"""* **Boss 的机制降级**（§194 起三幕各三只、数值全部来自 wiki，但四处机制只做到这样）：
  The Guardian 的 Mode Shift 是"HP ≤ 50% 时切一次"（wiki 是累计受伤 30，且当场改意图）；
  Hexaghost 的 Inferno 不升级已有的 Burn；Awakened One 的复活在 HP ≤ 25% 时改意图（内核没有死亡
  拦截），且场上没有两个 Cultist；Bronze Orb 的 Stasis（偷牌）与 Time Eater 的 Draw Reduction 没有原语。
  多段小兵（2 Orb / 2 Torch Head）**开局就在场上**，不是召唤的（遭遇名单是召唤物找招式表的唯一来路）。"""), (
"""  简化（前者 320 HP 版，后者 wiki 无页）。`Boss3` 池只有 1 只，所以 A20 的两场 Boss 打的是同一只。""",
"""  简化（前者 320 HP 版，后者 wiki 无页）。§194 起每幕的 Boss 池都是三只，A20 的两场可以不同。"""), (
"""| **内容** | **37 怪 / 27 遭遇 / 43 条卡行（26 张基础 + 17 张 `+`）/ 27 状态 / 79 敌人动作 / 13 遗物 / 33 药水（满池）/ 9 事件 / 10 张起始牌**。编译成 48,948 B 的 `rdcf` 镜像（core 镜像 40,900 B） |""",
"""| **内容** | **46 怪 / 33 遭遇 / 45 条卡行（28 张基础 + 17 张 `+`）/ 29 状态 / 117 敌人动作 / 13 遗物 / 33 药水（满池）/ 9 事件 / 10 张起始牌**。编译成 62,864 B 的 `rdcf` 镜像（core 镜像 52,528 B） |""")])

# ---------------------------------------------------------------- plan
section = """
---

## 194. 把三幕的 Boss 池对齐 wiki（每幕三只）

原先的账：`Boss` = Slime Boss、`Boss2` = The Champ、`Boss3` = Time Eater，而 §130 自己写过
"第 2/3 幕不是 wiki 的数值照搬，而是**机制上真的不同**" —— 也就是说这两只是**编的**（330 HP、
三招）。wiki 说每幕**三选一**。

### 194.1 这一节做了什么

| 幕 | 之前 | 之后 |
|---|---|---|
| 1 (`Boss`) | Slime Boss | Slime Boss / **The Guardian** / **Hexaghost** |
| 2 (`Boss2`) | The Champ（编的 330 HP、3 招） | The Champ（**wiki 的 420 HP、7 招**）/ **Bronze Automaton**（+2 Orb）/ **The Collector**（+2 Torch Head） |
| 3 (`Boss3`) | Time Eater | Time Eater（**wiki 的 4 招，含 Haste**）/ **Awakened One**（两阶段）/ **Donu & Deca**（一对） |

内容从 37 怪 / 27 遭遇 / 79 动作长到 **46 怪 / 33 遭遇 / 117 动作**；镜像 48,948 → 62,864 B。

### 194.2 三个"第一次"（都是既有机制的新用法，不是新机制）

1. **`sel.allAllies`** —— Donu 的 Circle of Power「全体敌人 +3 力量」、Deca 的 Square of Protection、
   Collector 的 Buff、Orb 的 Support Beam。⚠️ **`sel.allEnemies` 是敌方即"对方队伍"**
   （`targets::team_set(state, source, false, ..)`），Boss 用它会把 Buff 加在玩家身上 —— 战斗会变得
   *更容易*，而不是坏掉。所以这条有一个专门的测试（Donu 给自己和 Deca 各 3 层，玩家 0 层）。
2. **`repeat` 的计数是算出来的** —— Hexaghost 的 Divider `(玩家 HP / 12 + 1) × 6`：
   `repeat(add(divide(currentHealth(eventTarget), 12), 1))`。§146 引入 `node.repeat` 是为了 X 费牌，
   这是第一次让计数来自状态。测试在 70/12/11/0 四个血量点上各算一次（6/2/1/0 段）。
3. **`CardPlayed` 上"打出的是哪种牌"** —— Guardian 的 Sharp Hide（`card.hasTag.attack` → 3 伤害）
   与 Awakened One 的 Curiosity（`card.hasTag.power` → +力量）。§144 的 Enrage/Rage 用同一条形状，
   但都长在**玩家**身上；这是第一次用它在**敌人**身上反击玩家，而且**可被格挡**。

### 194.3 机制做不到的地方，逐条写进内容

每只 Boss 的 `AiNote` 都带一句"⚠️ 偏差"，`docs/sts-wiki-gap.md` §H 有汇总表。四条最要紧：

* **Guardian 的 Mode Shift**：wiki 是"累计受伤 30 → 20 Block + 当场改意图"；这里是"HP ≤ 50% 时
  改**下一轮**的意图"（意图每轮选一次）。防御态的 Roll Attack → Twin Slam → Whirlwind 与
  "Twin Slam 摘掉 Sharp Hide" 都精确。
* **Hexaghost 的 Inferno** 不升级已有的 Burn（没有"升级牌堆里的卡"节点）；Divider 读**结算时**的
  玩家 HP。7 招循环是**轮转对齐**的：`Actions[(round-1) % 7]` 从第 3 回合起正好是 wiki 的顺序 ——
  这条有测试（顺序被"理顺"时 Boss 照样打，只是招式顺序漂了）。
* **Awakened One 的复活**在 HP ≤ 25% 时改意图（内核没有死亡拦截），"移除所有 debuff"只按名摘掉
  Curiosity，场上没有 Cultist。
* **小兵开局在场**：`intent::locate_enemy` 给召唤物找招式表要靠遭遇名单（§138），而列进去就会生成 ——
  所以 `Spawn Orbs` / `Spawn` 被去掉，2 Orb 与 2 Torch Head 从第 1 回合就在。`Stasis`（偷牌）与
  Time Eater 的 `Draw Reduction` 没有原语。

### 194.4 判据

* **内容门**（独立第二份，数字全部来自 `native/wiki_asc/*.txt`）：`INV_MONSTERS` +9、
  `INV_ACTIONS` +38、`INV_CARDS` +2（`burn+` / `void`）、`INV_STATUSES` +2、变体 49 → **78**；
  三幕池的成员由 `INV_ACT_TABLES` + `INV_BOSS_POOL` 逐个钉住（多一个、少一个都红）。
* **内核行为**（5 + 3 条新测试）：三幕各三个 Boss 且每个都建得出来 / Hexaghost 的 9 回合招式序 /
  Automaton 的 A19 `Stunned→Boost`（**两侧都测**）/ Champ 的第 4 回合 Taunt 与半血后 Anger→Execute /
  Awakened One 的计数器翻阶段；Sharp Hide 只对 Attack 生效、Twin Slam 摘掉它 / Divider 在 4 个血量点上的
  段数 / Donu 的 Buff 落在两个 Boss 身上而玩家 0 层。
* **负控**：把 Sharp Hide 的 tag 改成 `skill` ⇒ 红在 `Sharp Hide 3 punishes an Attack, left 70 right 67`；
  把 Divider 的除数改成 10 ⇒ 红在 `hero at 70: 6 hits of 6 = 36, left 48 right 36`。
* **20/20 闸门绿**，单测 **848**（671 / 107 / 70）；四条对拍不变（182/182、62/62、124/124、394/394）。

### 194.5 踩到的坑（值得记）

内容里写 `divide{Left: ..., "Right": 12}` 而别处写 `Right: {"kind":"const",...}`，会让该字段在
派生时同时出现 `int` 与 `term` 两种存储类 ⇒ **整个字段退化 `F_JSON`**，内核求值报
`WrongKind("F_JSON")`，而报错点离"少包一层 `const`"有三层远。唯一在编辑期能看见它的地方是
`build.py` 报告里的 **"Fields that fell back to `F_JSON`"** 一行 —— 所以 `p194_helpers` 的算术构造器
现在自动把裸整数包成 `const`。
"""
src = io.open("docs/port-plan.md", encoding="utf-8").read()
assert "## 194." not in src
io.open("docs/port-plan.md", "w", encoding="utf-8", newline="").write(src.rstrip("\n") + "\n" + section)
print("patched docs/port-plan.md")

# ---------------------------------------------------------------- gap doc §H
gap = """
## H. 六只新 Boss 的机制降级（§194）

数字全部来自 `native/wiki_asc/<boss>.txt`（`action=raw`），**降级只在机制层面**，而且每一条都同时
写在内容的 `AiNote` 里（下一读者看的是那里，不是这份文档）。

| Boss | 做到了 | 与 wiki 的差 |
|---|---|---|
| The Guardian | 进攻 4 循环；Sharp Hide（`CardPlayed` + `card.hasTag.attack`，3 伤害，可格挡）；防御态 Roll Attack → Twin Slam → Whirlwind；Twin Slam 摘掉 Sharp Hide | **Mode Shift** 是"HP ≤ 50% 时切一次"，不是"累计受伤 30"；切换落在**下一轮**（意图每轮选一次） |
| Hexaghost | 第 1/2 回合 Activate / Divider；7 招循环轮转对齐；Divider = `(HP/12 + 1) × 6` | Divider 读结算时 HP；Inferno **不升级**已有的 Burn（没有"升级牌堆里的卡"节点） |
| The Champ | 420 HP；Heavy Slash / Face Slap / Defensive Stance / Gloat 循环；第 4 回合 Taunt；≤50% 后 Anger → Execute | 45/25/15/15 权重变成确定性循环；Anger 只按名清 Weak/Vulnerable/Frail；A19 的 "Gloat 换成 Defensive Stance" 未实现 |
| Bronze Automaton | 300 HP + Artifact 3；6 招循环；HYPER BEAM 45；A19 用 Boost 顶替 Stunned | 2 只 Orb **开局在场**（不是 Spawn Orbs）；Orb 的 `Stasis`（偷牌、死亡归还）未实现 |
| The Collector | 282 HP；Fireball/Buff 交替；第 4 回合 Mega Debuff | 25/45/30 权重变成 1:1；`Spawn` 去掉（2 只 Torch Head 开局在场） |
| Time Eater | 456 HP；Reverberate / Head Slam / Ripple；≤50% 的 Haste 回血一次 | Haste 不清 debuff；`Draw Reduction` 未实现 |
| Awakened One | 300 HP；Regenerate 10 + Curiosity 1；Slash/Soul Strike 循环；Rebirth → Dark Echo → Tackle/Sludge 交替 | Rebirth 在 **HP ≤ 25%** 时改意图（没有死亡拦截）；"移除所有 debuff"只摘 Curiosity；没有 Cultist |
| Donu & Deca | 一对（250 HP 各 + Artifact 2）；Donu 交替 Circle of Power / Beam；Deca 交替 Beam / Square of Protection | Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） |

另外一条**全局**的：A9 的 `AscHP`（如 The Champ 440）不会被精确命中 —— 跑层对 `MaxHealth` 施加的是
**百分比**（§159 的 A7/A8/A9 规则，420 → 525）。这条在 §194 之前就存在，基础血量现在是 wiki 的。
"""
src = io.open("docs/sts-wiki-gap.md", encoding="utf-8").read()
assert "## H." not in src
io.open("docs/sts-wiki-gap.md", "w", encoding="utf-8", newline="").write(src.rstrip("\n") + "\n" + gap)
print("patched docs/sts-wiki-gap.md (§H)")
