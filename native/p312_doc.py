"""§312 记账：`standard.malleable` + Snake Plant（Act 2 池 11 / 13）。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §312 `standard.malleable` 与 Snake Plant：一条反应式状态**不需要新内核分支**

§311 列出的两条 Act 2 缺口里，`snake_plant` 那条缺的是 `Malleable` —— wiki 原文
（`Malleable` 页 + `Snake Plant` 页两处）：

> *"Upon receiving attack damage, gains X Block. Block gain increases as Malleable is triggered.
> Resets at the start of your turn."*

### 312.1 为什么它能纯内容实现

一开始的假设是"这是新机制"（一个**会变的**反应式状态）。核对之后四样零件都已经存在：

| 需要 | 已有的东西 |
|---|---|
| 只在挨**攻击**时触发 | `DamageTaken` + `damage.isAttack`（Flying / Plated Armor 已在用） |
| 只有**掉血**才算 | `eventAmount > 0`（与 Plated Armor 同一口径） |
| "X 每次 +1" | 每战斗员计数器 `malleable_bonus`（Looter 的 `stolen_gold` 是同一机制） |
| 每回合重置 | `TurnStarted` 触发器把计数器置 0 |
| 给块 | `node.gainBlock` + `add(combatantStatusStacks, combatantCounter)` |

所以这一节**没有一行内核分支**：内容是"读状态层数 + 读计数器 + 相加 + 给块 + 计数器 +1"。
唯一的内核改动是**登记**（`status_catalog::has_behaviour` 里加一行），因为
`the_status_catalogue_is_honest` 要求"内容声明的每条状态要么有内核规则、要么声明为 inert" ——
它的原话是"否则它会**静默什么都不做**"。这条判据在这一轮当场抓住了一次（808 passed → 1 red）。

### 312.2 两条判错过的判据（都是我的错，不是实现的错）

1. **把蛇草打死了**：第一版每次 50 点 × 3 打 75 血的怪 —— 第二下就死，读到的是"尸体上的块"。
2. **把格挡当成了不消耗**：期望 `[3, 7, 12]`（累加），实际是 `[3, 4, 5]`。格挡会被伤害吃掉，
   所以每次命中后的读数就是"这次给的那一块"。⇒ 判据改成断言**给的块**递增（3/4/5），
   而不是断言累计值。

### 312.3 Snake Plant（wiki `Snake Plant` 页 + `SlaySpireDB`）

HP 75-79（A7 78-82）；开场 Malleable 3；`Chomp Chomp` 7×3（A2 8×3）、`Enfeebling Spores`
（Frail 2 + Weak 2）；65/35；不能连用 Chomp 三次、不能连用 Spores 两次（两条都用
`prev_move`/`last_move` 记账，与 Snecko 同一个形状）。

⚠️ **已知偏差**：wiki 的 A17 "第一次 Spores 之后改成固定 Chomp/Chomp/Spores 序列"**没做** ——
本移植的 A17 在其他怪物上一律只做到"禁令"那一层。写进 `docs/sts-wiki-gap.md` §D.3.2。

### 312.4 判据与负控

`malleable_grows_by_one_per_hit_and_resets_when_the_turn_starts`（rd-wasm，真打三下）四侧：
① 每击给的块 3 / 4 / 5；② 回合开始后又是 3；③ 毒（`DamageKind::Dot`）只吃块不给块；
④ 全程不把怪打死。

**负控两条**（`native/p312_negative.py`，改内容 → 重编镜像 → 跑判据）：
计数器不递增（`Relative: false`）⇒ 只给 3/3/3 ⇒ **红**；去掉 `TurnStarted` 清零 ⇒ 回合后给 4
⇒ **红**。两条缺一条，"会长"或"会清"就有一侧没人看。

### 312.5 账

内容：**52 怪 / 54 遭遇 / 147 状态 / 144 敌人动作 / 102 变体（89 动作）**；
镜像 **171,180 B**（core 134,744 B）；Act 2 普通池 **11 / 13**。
`rd-core` 809 / `rd-run` 194 / `rd-wasm` **154**（+1）；聚合闸门 **22/22**（`rust-units 1157`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§312 `standard.malleable`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1156') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1156', '  [int]$UnitsFloor = 1157'))
    print('§312 recorded; UnitsFloor 1157')


main()
