"""§297 文档：A4 `strike_dummy` / `velvet_choker` / `runic_dome`。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §297 A4：三件一起做，规则住在三个不同的地方

这一节的价值不在"又做了三件"，而在**同一批遗物里三条规则住在三处**，而每一处都有各自的
判据形状：

| 遗物 | 规则住哪 | 内容那一行 | 判据钉什么 |
|---|---|---|---|
| `strike_dummy` | **内容**（`DamageDealt / AddFlat 3 / RestrictSourceCardTag: strike`） | 真程序 | 那扇**标签门** |
| `velvet_choker` | 内核（`play.rs::card_limit_validator`，上限 6 是常量） | 开战状态 = 开关 | 第 7 张被拒 + 无状态时照打 |
| `runic_dome` | 内核 + 观测（`rd-wasm::refresh_intents`） | 开战状态 = 开关 | 观测里**就没有**意图 |

### 297.1 `strike_dummy`：零内核改动

`RestrictSourceCardTag` 那道门 §264 就实现了，而且**已有两个用户**（`akabeko` /
`double_damage`，标签都是 `attack`）。所以 `strike_dummy` 只是把标签换成 `strike`：

```
DamageDealt / AddFlat 3 / Priority 100 / RestrictSourceCardTag: strike
```

判据钉**两侧**：`strike` 6 → 9，`bash` 8 → 8。少了后半句，"所有牌都 +3" 也全绿。

### 297.2 `velvet_choker`：加一条校验器，而不是借法令

`Refusal::DecreeMaxCardsPerTurn` 已经存在，但它属于**法令**（`CombatRules`），而本内容的
`CombatRules` 全是 `ABSENT16`、且 `refuse_if_any_decree` 一票否决 —— 借它表达"遗物限制"
会让**法令**与**遗物**共用一个名字，而页面要把原因显示给玩家看。所以：

* `Refusal::CardLimitReached { cap, played }`（新，拒绝码 **19**）；
* `Validator::CardLimit`（Priority 200，id `standard.card_limit_validator`）——
  按 id 字节序排在 `one_attack_per_turn_validator` **前**面（`'c' < 'o'`），
  所以 `VALIDATOR_ORDER` 里它插在中间，而那条"执行序 = (priority, id) 升序"的既有判据
  因此要跟着多列一个名字（它本来就是**证明**那张表排对了，不是抄清单）。

上限 6 住在内核（与 `THE_BOOT` / `CHEMICAL_X` 同族）：它是这件遗物的**定义**，
而且今天只有它一个用户。有第二件同类遗物时再改成"内容给的数"。

### 297.3 `runic_dome`：看不见 = 观测里没有

"敌人意图"是**观测**里的东西（`refresh_intents` 每次重算）。要"看不见"，就该在观测里
**就没有** —— 而不是"画了再藏"：后者在 `?debug`、测试、截图里都能看见，而**玩家看不见的
规则等于不存在**。

★ 这条判据当场抓到一个真 bug：我第一版写 `combatant_has_status(&self.state, &id, …)`，
而那个循环里的 `id` 是**敌人** —— 状态在**英雄**身上，于是规则一次都没生效，而
"带遗物时意图被替换"的断言是我唯一的探针。
现在代码里那句注释写着 `⚠️ 状态在位英雄身上，而这个循环的 id 是敌人`，负控第 ④ 条
就是把 `&hero` 改回 `&id`。

### 297.4 判据与负控

| 判据 | 钉住 |
|---|---|
| `strike_dummy_only_boosts_cards_that_carry_the_strike_tag` | `strike` 6→9；`bash` 8→8 |
| `velvet_choker_stops_the_seventh_card_of_the_turn` | 前 6 张放行、第 7 张 `CardLimitReached{cap:6,played:6}`、被拒的牌不计数、拒绝码 19 与名字；**无状态时第 7 张照打** |
| `runic_dome_blinds_the_intent_observation` | 带遗物 ⇒ 意图文本被替换；不带 ⇒ 真意图；两者**必须不同** |

**负控 4 条全红**：上限改 99 / `>=` 改 `>` / `runic_dome` 查敌人（这轮真踩过）/
内容里去掉 `strike` 标签门。

### 297.5 账

内容遗物 **134 → 137**（缺 59 → 56）；状态 **133 → 136**；镜像 **164,672 B**；
`rd-core` **801**（+2）/ `rd-run` 181 / `rd-wasm` **143**（+1）；矩阵 853 行；
八道页面门 + `SOAK`；21/21。

### 297.6 A 项只剩两件

| 缺的事实 | 遗物 | 说明 |
|---|---|---|
| 战斗中治疗倍率 | `magic_flower` | `heal` 的数值改写（与 §263 的伤害改写同族） |
| `unplayable` 放行 | `medical_kit` / `blue_candle` | `validate_card_play` 的例外（与本节新加的校验器同一条链） |
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§297 A4' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''### F.16 遗物：X 费牌（§296）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.17 遗物：规则住在三处（§297）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `strike_dummy` | 带 "Strike" 的牌 +3 伤害 | **已做**（内容 `DamageDealt` + 来源卡标签门） | 一致 |
| `velvet_choker` | 每回合 +1 能量；最多 6 张 | **已做**（`card_limit_validator`，拒绝码 19） | 一致 |
| `runic_dome` | 每回合 +1 能量；看不见意图 | **已做**（观测里就没有意图） | 一致 |
| 出牌上限的数字 | 6 | 内核常量（与 `THE_BOOT` 同族） | 一致 |

### F.16 遗物：X 费牌（§296）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§296）', '（主计划 §1–§297）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
