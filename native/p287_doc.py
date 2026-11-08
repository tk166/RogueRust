"""§287 文档：port-plan + 缺口表 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §287 三件事件尾巴：条件 `card_damage` / 战后补偿 / 醒着的 Lagavulin

§286 的账上还留着三条"说明了的不对称"。这一节把三条都做成**机制**，而不是三条特例。

### 287.1 条件 `card_damage`（`Wing Statue` 的 `[Destroy]`）

wiki："Shown only if your deck holds a card dealing **10 or more damage per hit**."

条件词表原来只能问"有没有这张牌"（`card has <id>`），问不了"某张牌打多少"。现在加一个
**数值型** kind：

    Requires: [{Kind: "card_damage", Op: "at_least", Amount: 10}]

数字从**效果程序**里读（与执行器同一份数据，不是描述文本）：

* `ir::max_hit_damage(root)` —— 遍历程序取 `dealDamage` 的 `const` Amount 的最大值；
  `None` = 静态答不出（Amount 依赖状态、或藏在 `conditional`/`forEach*` 后面）⇒ 按 0 计，**不猜**；
* `Content::max_deck_hit_damage(deck)` —— 逐张查 `SEC_IDX`（`lookup_in(id, EK_CARD)`）取最大；
* `RunFacts.max_hit_damage` 由**调用方**（`rd-wasm`）算好递进来 —— `run_expr` 只做判定，
  "某张牌打多少"要读内容，这一层不该为了一格数字把内容表拖进来。

⚠️ 与 `rd-wasm::program_damage` 的分工：那个求**一次动作的伤害总和**（`EACT` 预览用），
这个求**单次命中的最大值**（"per hit"的条件用）。两个问题两个函数；把两者合成一个"伤害"
会让其中一边悄悄变错。

### 287.2 战后补偿（`Dead Adventurer`）

wiki：被伏击并打赢之后，"**还没搜到**的奖励"由这一场战斗补发；伏击前已经拿到的那一件
**从战斗奖励里去掉**（否则重复）—— 这也正是"这场精英能多掉 30 金币"的原因。

奖励流程是 `roll_reward(kind)`，它按档位掷、不知道"这一局少发了什么"。所以加两个运行层
字段，**由事件的进入效果写、由 `roll_reward` 消费**：

    fight_gold_bonus:<n>   这一场战斗的金币 + n（读一次就清）
    fight_no_relic          这一场战斗不掉遗物（读一次就清）

* **单写点**：事件效果（`EventEffect::FightGoldBonus` / `FightNoRelic`）；
* **单消费点**：`roll_reward`（所以它不可能漏进第二场战斗）；
* **清零多一处**：`begin_event` —— 欠账属于**一个**事件，开新事件就清（有一条判据钉着）。

内容侧：伏击段按"还剩下哪些奖励"分叉成 7 段（`dead_adventurer.ambush.<剩余集合>`），
每段的进入效果就是上面两条的取舍 —— 金币还没搜到 ⇒ `+30`；遗物已经搜到 ⇒ 不掉遗物。

### 287.3 醒着的 Lagavulin（`ENCT` 的"这次不睡"）

wiki：`Dead Adventurer` 的 Lagavulin "does not enter combat Asleep. It instead starts the fight
with Siphon Soul."

睡眠是**遭遇的静态属性**（`ENCT.Enemies[].StartingStatuses` 里那条 `standard.lagavulin_asleep`），
"醒着"是**这一次**的属性。改遭遇会连普通精英战一起改，所以入口做成"这一次用哪个池"：

    选项：{ Fight: "elite", Encounter: "EliteEvent" }

* `Encounter` 是 `EncounterTables` 里的**池名**（闭集，内容门查）；不写 ⇒ 按档位用本幕标准池；
* 池名进 `RunState` 的 `event_fight_pool`，与 `event_fight` 同一个清点（`mark_resolved`）——
  "要不要打 / 用哪个池 / 战后按哪档结算"三个答案必须出自同一份状态，否则存档/回放一半就漂；
* 内容：`EncounterTables.EliteEvent` = 三个 Act 1 精英，其中 `enc_lagavulin_awake`
  **没有**睡眠状态、`lagavulin_step` 初值 2 ⇒ 意图规则（0/1 → 攻击，2 → Siphon Soul）
  让第一回合就是抽魂。

命名约定：池名的**前缀**就是档位（`Elite*` ⇒ A8 的 HP 档），所以事件池叫 `EliteEvent`
而不是 `EventElite` —— 后者会被内容门算成"普通遭遇的 A7 档"，而它其实是精英。

### 287.4 内容门的四条新判据（都是"静默无效"的形状）

| 判据 | 钉住 |
|---|---|
| `REQUIRES_KINDS` += `card_damage` | 条件词表与内核同一份（否则条件读到就是 `UnknownKind`） |
| `INV_EVENT_VARIANTS` | 事件变体遭遇**必须登记**，且只许与原型在 `StartingStatuses`/`Counters` 上不同；同时它**不算**进 wiki 的遭遇数 |
| `encounters.ids` 的 `stray` 分支 | 池子外的遭遇 id **必须**是登记过的变体（"凭空多一个遭遇"会被拦） |
| `EncounterTables.EliteEvent` 的 hop 字面量 | 内核真的读这个池（`inert.undeclared` 那条抓的） |

### 287.5 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_unknown_room_events_are_readable`（§287 段） | 真实镜像上 `max_deck_hit_damage`：`bash+` = 10、`strike` = 6；`[Destroy]` 在 `bash+` 下可选、在 6 点牌组下**不可选** |
| `the_fight_reward_debt_is_paid_once` | 精英 `{low}..={high}` **+30**、遗物被压掉；第二场恢复正常 |
| `opening_an_event_clears_the_debt` | 上一件事的欠账不漏进下一场 |
| `the_ambush_lagavulin_starts_awake_with_siphon_soul` | 事件池抽到的 Lagavulin 无睡眠状态、第一回合 `lagavulin.siphon_soul`（且不是 `sleep`） |
| `browser_test` §287 块 | 起始牌组（单次最高 8）下 `[Destroy]` **不画**、另两个照画；点被藏起来的槽 ⇒ `-2` 且屏幕不变 |

**负控 3 条全 RED**：① `card_damage` 恒成立；② 欠账不消费；③ 事件战斗不看 `Encounter` 池
（不看池就会抽到睡着的那一份，第一回合变成 `sleep`）。

### 287.6 账

`rd-core` 797（其中 §287 段在 `the_unknown_room_events_are_readable` 里）/ `rd-run` **159** /
`rd-wasm` **132**；遭遇 **44 → 45**（+`enc_lagavulin_awake`，不进 wiki 计数）；step 66 → 72
（伏击分叉成 7 段）；镜像 **160,344 B**（core 126,316 B）；八道页面门 + `SOAK`；21/21。

### 287.7 还没做的

* `Dead Adventurer` 的**楼层门槛**（wiki：第 7 层之后才出现）：事件池还不能按楼层筛。
* `The Colosseum`：同一套"事件开战斗"的机制可以做，缺的是"打完**回到事件**"（我们是"战斗
  结算房间"）。
* `card_damage` 只看**基础伤害**：力量/`Wreath of Flame` 之类的加成不算 —— 与 wiki 的
  "printed damage per hit"一致，但如果将来条件想表达"当前伤害"，要另加一格。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### G. ★ 基础值偏差'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.7 事件尾巴（§287）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Wing Statue` `[Destroy]` 的条件 | 牌组里有单次 ≥10 伤害的牌 | **已做**（`Requires: card_damage at_least 10`，从效果程序读） | 一致 |
| `Wing Statue` 条件的口径 | "printed damage per hit" | 基础伤害（力量/附魔不算） | 一致（与 wiki 的措辞同义） |
| `Dead Adventurer` 战后补偿 | 补发"还没搜到"的奖励，且已搜到的从战斗奖励里去掉 | **已做**（`fight_gold_bonus` / `fight_no_relic`） | 一致 |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡**，第一回合 Siphon Soul | **已做**（`Encounter: "EliteEvent"` + `enc_lagavulin_awake`） | 一致 |
| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | 事件池无按楼层筛 | 缺 |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§286）', '（主计划 §1–§287）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§287 doc + gap rows + README')


main()
