"""§329 文档：Boss 相位。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §329' not in t
t = t.rstrip('\n') + '\n' + """
## §329 Boss 相位：先证明"大部分已经在"，再补三处真缺口

⚠️ 又一次先纠正过期结论：`FACT.md` 里"还不能 Boss 分裂/相位（除 Slime Boss）"这句是错的。
对着 `native/wiki_asc/*.txt` 逐条核，六个 Boss 的相位机制**基本都在**：

| Boss | 相位规则 | 状态 |
|---|---|---|
| The Champ | 每 4 回合 Taunt；HP ≤ 50% 用 Anger（**清三种 Debuff** + 加力量）→ 下一回合 Execute；A19 把 Gloat 换成 Defensive Stance 且连用则回退 | 已有 |
| Awakened One | `unawakened` 守卫（致命伤留 1 血，内核实现）→ 意图变 Rebirth → 回满血 + 失 Curiosity；二阶段 Dark Echo 起手；Cultist 逃跑 | 已有（缺清 Debuff，见下） |
| The Collector | 第 1 回合 Spawn、第 4 回合 Mega Debuff；Buff 不能连用、Fireball 不能三连 | 已有（缺"再召唤"分支，见下） |
| Bronze Automaton | Spawn Orbs → Flail/Boost/Flail/Boost/HYPER BEAM/Stunned；A19 用 Boost 顶替 Stunned；Orb 的 Stasis | 已有 |
| Time Eater | Haste（HP ≤ 50% 且一次性）回 50% 血；不连用规则 | 已有（缺清 Debuff，见下） |
| Donu & Deca | Donu 交替 Circle of Power / Beam；Deca 交替 Beam / Square of Protection；Artifact | 已有 |

真缺三处，都是"形状在、规则漏"：

### 1/2. `awakened_one.rebirth` 与 `time_eater.haste` 少了 "Removes all Debuffs"

wiki 的原话分别是 *"Heals to full HP. **Removes all Debuffs**. Loses Curiosity."* 与
*"**Removes all Debuffs**. Heals to 50% HP. (A19: gains 32 Block.)"* —— 内容只做了治疗那半。
用 §310 为 `orange_pellets` 加的 `node.removeDebuffs` 补上（按**定义极性**删，Artifact 不拦移除）。

### 3. The Collector 少了"再召唤"分支，且 `spawn` 无条件召 2 个

wiki：*"Summons **up to 2** Torch Heads"*、*"Can only have two Torch Heads summoned at a time."*、
分支表"0-1 只活着：Spawn 25 / Fireball 45 / Buff 30"、"两只都活着：Fireball 70 / Buff 30"。
内容只有后者 —— 也就是说**两只 Torch Head 死光后她再也不会召唤**，而那正是这场 Boss 战的核心规则。

两处修法：

* 意图侧加一条 `intent.enemyAliveCount <= 2` 的规则（priority 45，夹在连用守卫 54/55 与
  兜底 40 之间），权重 25/45/30；
* 动作侧把两个无条件 `createCombatant` 换成"3 个友军 ⇒ 0 只 / 2 个 ⇒ 1 只 / 否则 2 只"的
  两层 `node.conditional`。

⚠️ 这里踩了一个坑并且**判据当场抓住**：第一版用 `sel.allEnemies` 数，而它的语义是
**异队**（`targets.rs` 的 `team_set(state, source, false, …)`）—— 从 Collector 眼里数到的是
玩家。于是"已经有两只"时又召了两只（行为判据报 `left: 4, right: 2`）。改成 `sel.allAllies`
（同队，含自己）才对。

### 判据

* `the_two_phase_heals_also_cleanse_debuffs`（rd-wasm）：给 Boss 挂 3 种 Debuff，跑一次动作，
  要求**一个不剩**；同时断言血真的回了（否则"清空所有状态"也会绿）。
* `the_collector_summons_only_up_to_two_torch_heads`（rd-wasm）：开局 0 只 → +2、已满 → +0、
  杀掉一只 → +1。只测第一次的话，"无条件召 2"的实现照样绿。
* `the_collector_draws_by_weight_and_never_buffs_twice_in_a_row`（rd-core）扩成**两个分支**：
  "只剩她"时 25/45/30、"两只都在"时 70/30 且 **Spawn 不可达**。它原来把 `spawn` 当"意外招式"
  panic —— §329 的规则一落地它就在**正确的位置**红了，这正是判据写在行为上的用法。

负控 5 条全红：rebirth 不清 Debuff（行为 + 清单两侧）、haste 不清 Debuff（清单）、
spawn 回到无条件 2 只（行为）、删掉"0-1 只"分支（`Spawn took 0/400 = 0.00, wiki says 25%`）。

数字：`rd-core 812 / rd-run 214 / rd-wasm 179`、units **1205**（下限 1203 → 1205）；
四条对拍不动（`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §329 ok')

g = io.open(GAPS, encoding='utf-8').read()
old = '| **招式表升档** |'
idx = g.index(old)
row_end = g.index('\n', idx)
note = ('\n| **Boss 相位** | §329：六个 Boss 的相位规则逐条对过 wiki —— Champ 的 Anger/Execute、'
        'Awakened One 的 unawakened→Rebirth、Collector 的两条召唤分支、Automaton 的 A19 Boost 顶替 '
        'Stunned、Time Eater 的一次性 Haste、Donu/Deca 的交替；本轮补了 Rebirth/Haste 的 **清 Debuff**'
        '与 Collector 的 **再召唤 + up to 2** | — （余下只有"A19 的具体数值"这类，已由 `[7]`/`[7b]` 钉住） |')
g = g[:row_end] + note + g[row_end:]
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g)
print('gap doc ok')
