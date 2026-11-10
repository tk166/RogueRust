"""§321 文档 —— README / wiki-gap / event-gaps / port-plan。

数字来自 `native/gap_check.py` 的 pastable 区块（events 29 = 三幕池 10+9+10；镜像 181,940 /
core 145,008 B）。三幕事件的 wiki 清单到此 **7/7 全齐**。
"""

import io

README = 'README.md'
WIKI = 'docs/sts-wiki-gap.md'
GAPS = 'docs/event-gaps.md'
PLAN = 'docs/port-plan.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(README, encoding='utf-8').read()
t = sub(t, '**24 个事件**（三幕池 10+9+8 = 27 条，跨幕复用 3 条）',
        '**26 个事件**（三幕池 10+9+10 = 29 条，跨幕复用 3 条）', 'README events')
t = sub(t, '编译成 180,936 B 的 `rdcf` 镜像（core 镜像 144,004 B）',
        '编译成 181,940 B 的 `rdcf` 镜像（core 镜像 145,008 B）', 'README image')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'enemy actions 159 / relics 152 / potions 33 / events 27 (10+9+8) / start deck 10',
        'enemy actions 159 / relics 152 / potions 33 / events 29 (10+9+10) / start deck 10',
        'wiki-gap counts')
t = sub(t, '`27` 是三个幕的事件池之和（`10+9+8`）', '`29` 是三个幕的事件池之和（`10+9+10`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

t = io.open(GAPS, encoding='utf-8').read()
t = sub(t,
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **5**（§318 补了 `Mysterious Sphere` / `Winding Halls`，§319 补了 `Falling`，§320 补了 `Sensory Stone`） | 其余 **2**：`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |',
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **7 = 全部**（§318 `Mysterious Sphere` / `Winding Halls`，§319 `Falling`，§320 `Sensory Stone`，§321 `Mind Bloom` / `Tomb of Lord Red Mask`） | — |',
        'gap act3 row')
t = sub(t,
        '| `mind_bloom` | 3 | **wiki 的四个选项**（§311 更正：旧版这一格写错过）：① *I am War* —— 打一场第 1 幕 Boss，得稀有遗物 + 50（A15 25）金币；② *I am Awake* —— 升级所有牌 + `Mark of the Bloom`（**不能治疗**）；③ *I am Rich* —— 999 金币 + 2 张 `Normality`；④ *I am Healthy* —— 回满血 + `Doubt`；第三项按血量在 Rich / Healthy 之间换 | 大：要 `upgrade_all`、两条新诅咒、`mark_of_the_bloom`（"不能治疗"的载体）与"打一场**第 1 幕** Boss"（事件开战斗有了，**指定 Boss 池**还没有） |',
        '| ~~`mind_bloom`~~ | 3 | **§321 已做**：`Fight: "boss"` + `Encounter: "Boss"`（第 1 幕 Boss 池）、`upgrade_all`、`mark_of_the_bloom`（`NoHeal`）、两个诅咒、以及 `floor` 条件（第三项按层号换；本幕内 35–40 ⇒ `at_most 6`、41+ ⇒ `at_least 7`） | — |',
        'gap mind_bloom row')
t = sub(t,
        '| `tomb_of_lord_red_mask` | 3 | 事件级"有红面具" + `gold_all`（**§300 已做**）⇒ 现在只差事件级条件与内容 |',
        '| ~~`tomb_of_lord_red_mask`~~ | 3 | **§321 已做**（纯内容）：`relic has red_mask` ⇒ +222 金币；`gold at_least 1` ⇒ `gold_all` + `relic:red_mask` | — |',
        'gap tomb row')
t = sub(t, '| `upgrade_all`（升级所有牌） | `mind_bloom`（半血那条已经能用 `upgrade_random`） |',
        '| ~~`upgrade_all`（升级所有牌）~~ | **§321 已做**（`mind_bloom`） |',
        'gap upgrade_all row')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps ok')

t = io.open(PLAN, encoding='utf-8').read()
assert '## §321' not in t, 'port-plan already has §321'
entry = """
## §321 `tomb_of_lord_red_mask` + `mind_bloom` —— 三幕事件 7/7

### Tomb of Lord Red Mask（纯内容）

| 选项 | 条件 | 效果 |
|---|---|---|
| Don the Red Mask | `relic has red_mask` | +222 金币（遗物留着） |
| Offer all Gold | `gold at_least 1` | `gold_all`（全失）+ `relic:red_mask` |
| Leave | — | `nothing` |

`red_mask` 的遗物效果（开战给全体 1 层 Weak）§224 就已经实现了，所以这条事件**一行内核都没动**。

### Mind Bloom（三件新东西）

| 选项 | 内容 |
|---|---|
| I am War | `Fight: "boss"` + `Encounter: "Boss"`（**第 1 幕** Boss 池）+ `fight_gold_bonus` 50（A15 25）+ `fight_relic_rarity:rare` |
| I am Awake | `upgrade_all` + `relic:mark_of_the_bloom` |
| I am Rich | `Requires: floor at_most 6` ⇒ +999 金币 + 2 张 `normality` |
| I am Healthy | `Requires: floor at_least 7` ⇒ `heal_full` + 1 张 `doubt` |

三件新东西：

1. **`Fight: "boss"` ⇒ 3**（原来只有 `monster`=1 / `elite`=2）。它不只是文案：`rd-wasm` 的
   `fight_kind` 现在把事件的 Boss 档位也报成 `FightKind::Boss`，于是 `pantograph` /
   `slavers_collar` 在 `[I am War]` 里真的生效 —— wiki 明写 *"Pantograph and Slaver's Collar
   will work as if it is another Boss encounter"*。
2. **`upgrade_all`**（新原子，无问句）：把**有 `+` 行且还没升**的牌全升掉；已经是 `+` 或没有
   `+` 行的保持原样（与 `Upgrade` 同一条规则，靠 `upgrade_at` 查池子）。
3. **`mark_of_the_bloom` 从 `NoRest` 改成 `NoHeal`** —— 这是一个**更正**：wiki 说它
   *"You can no longer heal"*，它不禁休息。可观察差别做成了一对判据：`campfire_options().rest`
   仍是 true，但 `rest()` 回 0 点。规则落在**唯一的治疗汇** `heal_after_combat` 上，
   所以休息 / `heal` / `heal_pct` / `heal_full` / 遗物拾取（`blood_vial`）一次全覆盖。
4. **条件原子 `floor`**（本幕内层号，数值型）。wiki 的第三项按**绝对**楼层换（35–40 / 41+），
   而我们的层号是**本幕内**的（`RunState::floor` 与 `EventTables.MinFloor` 同一个口径），
   所以内容写 `at_most 6` / `at_least 7`。⚠️ 这个换算**写死在内容里**，没有别的判据能核对它 ——
   它依赖"第三幕从绝对 35 层起算"这条外部知识。

判据：`upgrade_all` 逐张（含"没有 `+` 行的牌原样"）、`mark_of_the_bloom` 五条治疗路径全 0
（并且先在无遗物的局上证明同样的调用**真的会回血**）、`floor` 两侧 + 一条**换事实再问一次**
的判据（常量 6 在单组事实上与真值不可区分 —— 这一条是负控没红之后补的）。

负控三条各红在预期位置：`blocks_healing` 恒 false / `upgrade_all` 空操作 /
`floor` 恒 6（第三条第一版**没被抓住**，补了换事实的判据才红）。

⚠️ 已知缺口（写在这里而不是藏起来）：

- `mark_of_the_bloom` 只挡**运行层**的治疗；战斗**内**的治疗（药水、战斗侧的回合末触发）
  走的是战斗状态机，不受它影响。
- `[I am War]` 的"第 1 幕 Boss"用的是内容里的 `EncounterTables.Boss`（第 1 幕），
  与"本幕 Boss"靠池名区分；事件战斗的 `After` 为空 ⇒ 打完直接回跑图（与 Mysterious Sphere 同）。

数字：事件 **26** 个（三幕池 10+9+10 = 29 条）、镜像 181,940 / core 145,008 B、
`rd-core 811 / rd-run 206 / rd-wasm 162`、units 1180（下限 1176 → 1180）。
**Act 3 事件 5/7 → 7/7（wiki 清单全齐）**，Act 2 6/13。
"""
t = t.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan ok')
