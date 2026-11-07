"""§275 文档 + README 数字。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'

DOC = """
---

## §275 遭遇：先纠正一条旧结论，再补 Act 1 硬池的三场

### 275.1 ★ 那条"精英只有 4 个"是**错的**（FACTS 与 §256 都写过）

开工前先核对，结论是**五个精英遭遇早就在内容里**，而且不是空壳：

| 遭遇 | 怪物 | 关键机制（都在） |
|---|---|---|
| `enc_lagavulin` | lagavulin 109（A8 112） | 睡 → 受伤转晕（`standard.lagavulin_asleep` 的 `DamageTaken` 触发器）→ 醒后 `Attack/Attack/Siphon Soul`（`lagavulin_step` 计数器）；`stunned` 空动作 |
| `enc_book_of_stabbing` | book_of_stabbing 160（A8 168） | `6×N`（A3 `7×N`）；`book_stab_single_bump` 在 A18 变 1 ⇒ **N = 回合+1**；不能连 3 次 Multi Stab、不能连 2 次 Big Stab |
| `enc_slavers` | taskmaster 54 / slaver_red 46 / blue_slaver 46 | 三个一组；`entangle_ready`；A17 的"不连续 Rake/Scrape 两易伤" |
| `enc_nemesis` | nemesis 185（A8 200） | `phantom_veil`（隔回合无实体）；Tri Attack `6×3`（A3 `7×3`）；Tri Burn 3 张（A18 5 张）；不连续 Burn/Scythe、不连 3 次 Tri Attack |
| `enc_reptomancer` | reptomancer 180（A8 190）+ 2× dagger 20 | `createCombatant(dagger, 22)`；A18 **一次召 2 把**；`aliveEnemies ≥ 5` ⇒ 不再召唤（=最多 4 把） |

而且六条**具名运行时判据**都在 `rd-wasm/src/lib.rs` 且通过：
`the_five_elite_encounters_match_the_wiki_numbers`（`rd-core`）、
`lagavulin_wakes_when_it_loses_health…`、`nemesis_never_repeats_burn_or_scythe…`、
`reptomancer_switches_to_snake_strike_when_four_daggers_are_out`、
`book_of_stabbing_multistab_starts_at_two_hits`、`blue_slaver_never_rakes_twice_in_a_row_at_a17`、
`slaver_red_scrape_applies_two_vulnerable_from_a17`。

⇒ 这一节**没有重做**它们。真正缺的遭遇在**弱池**。

### 275.2 权威表：Act 1 有两个池

wiki.gg `Exordium` 与 slayspiredb `Exordium` 一致 —— Act 1 是 **Easy**（前三场：
Cultist 2 / Jaw Worm 2 / 2 Louse 2 / Small Slimes 2）+ **Hard**（Gang of Gremlins 1 /
Large Slime 2 / Swarm of Slimes 1 / Blue Slaver 2 / Red Slaver 1 / 3 Louse 2 /
2 Fungi Beasts 2 / Exordium Thugs 1.5 / Exordium Wildlife 1.5 / Looter 2）。

本移植只有**一个** `Weak` 池（easy 与 hard 合并，既有简化）。按表对照后，这一节补
**只用现有怪物**的三场：

| 遭遇 | 构成 | 权重（wiki 2 ⇒ 14） |
|---|---|---|
| `enc_three_louses` | 1 绿 + 2 红 | 14 |
| `enc_two_fungi_beasts` | 2 | 14 |
| `enc_blue_slaver` | 1（46 / A7 48） | 14 |

### 275.3 两个错（都是这一节自己踩的，值得记）

**(1) 遭遇里的 `IntentRules` 是 roster 的**副本**，必须逐字一致。**
第一版我给新行写了 `IntentRules: []`，内容门报
`the inline IntentRules differ from the roster's copy`。恶心之处：**运行时不会崩** ——
空规则的怪**永远用 `Actions` 的第一条**，行为悄悄退化。
修法：**克隆**同 id 的既有遭遇行（没有就克隆 roster 行），只改 `MaxHealth`/`MaxHealthAsc`/`Position`。

**(2) `MAX_ENEMY_SLOTS = 4`，而 `Swarm of Slimes` 要 5 个槽。**
那是**容量常量 = 语义**（观察向量按它排布、页面 122 格偏移跟着它走），所以这一节**不做**它。
⇒ 写进缺口，而不是把上限改大再回来收拾四道页面门。

### 275.4 还缺的三件（写在缺口文档里）

| 缺的 | 缺什么 |
|---|---|
| `Swarm of Slimes`（3 spike S + 2 acid S） | **第 5 个敌人槽** ⇒ 要抬 `MAX_ENEMY_SLOTS`（观察向量/页面/存档一起动） |
| Large Slime（Spike L / Acid L） | **L 系史莱姆怪物**（我们只有 M/S） |
| Exordium Thugs / Wildlife | **动态组合规则**（"First enemy: Louse 或 Medium Slime；Second: Slaver/Cultist/Looter"）—— 我们的遭遇是静态列表 |

顺带记一条：`acid_slime_s` 这个怪物**之前没有任何遭遇用到**（只有 roster 行），
这一节本来要用它（Swarm），现在仍未被使用 —— 它排在"下一个要 5 槽的遭遇"里。

### 275.5 判据

`the_act_one_hard_pool_encounters_match_the_wiki_numbers`（`rd-core`，读内容镜像）：
三场的**敌人个数与顺序**、每只的 **wiki HP**。故意钉住"1 绿 2 红"这个组合 ——
原作每只独立掷色，静态内容只能写一种，钉住它才会在"哪天改成随机"时有人来看。

### 275.6 账

遭遇 **35 → 38**；`Weak` 池 **9 → 12** 条；`rd-core` **789** / `rd-run` 146 / `rd-wasm` 123；
内容 124 状态 / 115 遗物 / 293 卡行 / 130 动作；镜像 145,728 B（core 112,276 B）；
四条对拍全过；四道页面门 PASS（`ACT1_SLICE` 自己换了种子 404 —— 弱池一变，走图就重掷）；
`COVERAGE_MATRIX` 791 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    # 缺口文档：把"遭遇"的现状写清楚（§D.2 后面加一小节）
    gap = io.open(GAP, encoding='utf-8').read()
    anchor = '### G. ★ 基础值偏差：§191 修掉了 8 条，剩 3 条是写明了的简化'
    section = '''### D.3 遭遇：Act 1 的池子与还缺的三件（§275）

Act 1 在 wiki 里是**两个**池（Easy 前三场 + Hard），本移植只有一个 `Weak`（既有简化）。
§275 补了"只用现有怪物"的三场（`3 Louses` / `2 Fungi Beasts` / `Blue Slaver` solo），
现在 `Weak` 池 12 条、遭遇 38 个。

还缺三件，各缺一块**别的东西**（不是"抄一条遭遇"）：

| 缺的 | 缺什么载体 |
|---|---|
| `Swarm of Slimes`（3 spike S + 2 acid S） | **第 5 个敌人槽**：`MAX_ENEMY_SLOTS = 4`，而观察向量/页面偏移/存档都按它排布 |
| Large Slime（Spike L / Acid L） | **L 系史莱姆怪物**（只有 M/S 两种） |
| Exordium Thugs / Wildlife | **动态组合规则**（"First enemy: Louse 或 Medium Slime…"），我们的遭遇是静态列表 |

⚠️ 五个**精英**遭遇（Lagavulin / Book of Stabbing / Slavers / Nemesis / Reptomancer）
**早就在内容里**且各有具名运行时判据 —— 旧文档说"缺这五个"是过期信息（§275.1）。

'''
    assert gap.count(anchor) == 1
    gap = gap.replace(anchor, section + anchor)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(gap)

    # README
    r = io.open(README, encoding='utf-8').read()
    r = r.replace('/ 35 遭遇 /', '/ 38 遭遇 /')
    r = r.replace('（主计划 §1–§274）', '（主计划 §1–§275）')
    r = r.replace('145,220 B 的 `rdcf` 镜像（core 镜像 111,772 B）。',
                  '145,728 B 的 `rdcf` 镜像（core 镜像 112,276 B）。')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§275 doc + gap D.3 + README')


main()
