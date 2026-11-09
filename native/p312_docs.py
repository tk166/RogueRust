"""§312（三）：文档 —— Snake Plant 进池子、Malleable 的账、数字。

数字全部来自 `gap_check.py` 的输出（`52 / 54 / 147 / 144 / 102 / 89 / 171,180 / 134,744`）。
"""
import io

ROOT = 'D:/Vibe/sts-tui/'
GAP = ROOT + 'docs/sts-wiki-gap.md'
README = ROOT + 'README.md'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # §1.1 pastable
    patch(GAP, '''monsters 51 / encounters 53 / cards 293 (base 154 + plus 139) / statuses 146 /
enemy actions 142 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 101 over 88 actions
image full   content.sts.rdcf            169820 B
image core   content.sts.core.rdcf       133660 B''',
'''monsters 52 / encounters 54 / cards 293 (base 154 + plus 139) / statuses 147 /
enemy actions 144 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 102 over 89 actions
image full   content.sts.rdcf            171180 B
image core   content.sts.core.rdcf       134744 B''')

    # §D.3.1：Snake Plant 从 ❌ 变 ✅，并补两条解释
    patch(GAP, '''| Snake Plant | Hard | 6 | ❌ 要 `standard.malleable` |''',
'''| Snake Plant | Hard | 6 | ✅ §312（`standard.malleable` + 新怪物） |''')

    patch(GAP, '''三条缺口各缺什么（**不是"没抄"**）：

1. **`mugger`** —— 全新怪物。它和 Looter 共享 `stolen_gold` / `carryAwayStolenGold`，但它的
   招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；照 Looter 的骨架写等于
   **发明**一条规则，所以等到能核对清楚时再做。
2. **`snake_plant`** —— 要 `standard.malleable`：受到**攻击**伤害时获得 X 块、且每次触发 X
   变大、回合开始重置。内核今天没有这条"会变的反应式状态"，是**新机制**。
3. **`centurion` + `mystic`** —— `Protect` 要给 **Mystic**（不是自己、也不是全体）挂 15 块；
   `Mystic` 的 `Heal` 要给全体敌人回 16（这条已有：`sel.allAllies` + `heal`）。前者缺
   "按定义挑一只友军"的选择器 —— `sel.allAllies` 会把 Centurion 自己也算上。''',
'''两条缺口各缺什么（**不是"没抄"**）：

1. **`mugger`** —— 全新怪物。它和 Looter 共享 `stolen_gold` / `carryAwayStolenGold`，但它的
   招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；照 Looter 的骨架写等于
   **发明**一条规则，所以等到能核对清楚时再做。
2. **`centurion` + `mystic`** —— `Protect` 要给 **Mystic**（不是自己、也不是全体）挂 15 块；
   `Mystic` 的 `Heal` 要给全体敌人回 16（这条已有：`sel.allAllies` + `heal`）。前者缺
   "按定义挑一只友军"的选择器 —— `sel.allAllies` 会把 Centurion 自己也算上。

### D.3.2 Malleable（§312）

`Malleable X`（wiki 两处：`Malleable` 页与 `Snake Plant` 页）= "受到**攻击伤害**时获得 X 块，
X 随着触发**+1**，每回合开始**重置**"。它**可以纯内容实现**，因为零件都已有：

| 需要 | 已有的东西 |
|---|---|
| 只在挨攻击时触发 | `DamageTaken` 触发器 + `damage.isAttack`（Flying / Plated Armor 在用） |
| 只有**掉血**才算 | `eventAmount > 0`（与 Plated Armor 同一口径） |
| "X 每次 +1" | 每战斗员计数器 `malleable_bonus`（Looter 的 `stolen_gold` 同一种机制） |
| 每回合重置 | `TurnStarted` 触发器把计数器置 0 |
| 给块 | `node.gainBlock` + `add(combatantStatusStacks, combatantCounter)` |

判据 `malleable_grows_by_one_per_hit_and_resets_when_the_turn_starts` 四侧：给 3/4/5、回合
开始后又给 3、毒（`DamageKind::Dot`）只吃块不给块。**负控两条**（计数器不递增 / 去掉回合清零）
都红 —— 只测"会长"会放过"不清零"的实现，反之亦然。

⚠️ **已知偏差**：wiki 的 A17 "第一次 Spores 之后改成固定 Chomp/Chomp/Spores 序列"**没做**。
本移植的 A17 在其他怪物上一律只做到"禁令"那一层（§187–§192），这条也是同一类。''')

    # README 数字与池子条数
    patch(README, '**51 怪 / 53 遭遇 /', '**52 怪 / 54 遭遇 /')
    patch(README, '146 状态 / 142 敌人动作', '147 状态 / 144 敌人动作')
    patch(README, '**88 个动作有升阶变体**（101 个变体）。编译成 169,820 B 的 `rdcf` 镜像（core 镜像 133,660 B）。',
                 '**89 个动作有升阶变体**（102 个变体）。编译成 171,180 B 的 `rdcf` 镜像（core 镜像 134,744 B）。')
    patch(README, '**51 怪 / 53 遭遇**；', '**52 怪 / 54 遭遇**；')
    patch(README, '**Act 2 普通池 10 条**（wiki 的 13 条里', '**Act 2 普通池 11 条**（wiki 的 13 条里')
    patch(README, '''  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池 10 / 13** —— 缺
  `snake_plant`（要 `standard.malleable`）、`centurion` + `mystic`（要"指定某一只友军"的选择器）、
  `2 Thieves`（要 `mugger`）。逐条见 `docs/sts-wiki-gap.md` §D.3.1。''',
'''  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池 11 / 13** —— 缺
  `centurion` + `mystic`（要"指定某一只友军"的选择器）与 `2 Thieves`（要 `mugger`）。
  逐条见 `docs/sts-wiki-gap.md` §D.3.1。''')
    print('docs updated for §312')


main()
