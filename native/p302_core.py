"""§302 `strange_spoon`：打出即消耗的牌有 50% 概率改为进弃牌堆。

## 切口选在**落区**，因为那里是唯一收敛点

wiki 的 "Interactions" 一节把边界写得很死（这是它最有价值的部分）：

| 情形 | 受影响 |
|---|---|
| 打出时消耗（`Offering` / `Impervious` / `Limit Break`） | **是** |
| `Corruption` 让 0 费技能消耗 | **是** |
| `Havoc` / `Omniscience` **打出**的牌（临时获得消耗） | **是** |
| `Medical Kit` / `Blue Candle` 放行的不可打牌 | **是** |
| 回合末因 `Ethereal` 消耗 | 否 |
| 被别的效果逼着消耗（`Burning Pact` / `Fiend Fire` / `Elixir`） | 否 |
| 不可打牌被 `Havoc` 消耗（不算"被打出"） | 否 |

前四行的共同点是**它们都在 `plan_play` 的落区决策里**（`override_destination` / `corruption_destination`
/ `unplayable_is_free`）；后三行根本不经过出牌计划（`MoveCardToZone` 请求 / 被拒后放回）。
所以切口就是 `PlayPlan::destination` —— 不是发明一条规则，而是**它已经在那一格里**。

## 随机数必须在 `apply` 里掷，不能在 `plan_play` 里掷

`plan_play` 是**纯读**（`&CombatState`）：它的存在意义是"拒绝 ⇒ 一个字节都不改"。
在计划里掷骰会让一次**被拒**的出牌也消耗随机流 —— 同一颗种子随后整场错位，而没有任何
东西会红。所以掷骰放在 `apply_plan_in_chain`，且**在付款成功之后**（付不起的牌没被打出，
它不该消耗任何东西）。

## 值是 wiki 的常量，开关是**状态**

内容那一行 `standard.strange_spoon` 是载体（`Triggers: []`，与 `medical_kit` 同形状），
遗物行用 `StartCombatStatus` 在开战时给它；内核认状态 id，百分比是常量。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 常量（与 MEDICAL_KIT/BLUE_CANDLE 同处）
    patch(PLAY, '''pub const BLUE_CANDLE_STATUS: &str = "standard.blue_candle";''',
                '''pub const BLUE_CANDLE_STATUS: &str = "standard.blue_candle";
/// §302：`strange_spoon` —— "Cards which Exhaust when played will instead discard 50% of the time."
pub const STRANGE_SPOON_STATUS: &str = "standard.strange_spoon";
/// §302：那 50%。**只影响"打出即消耗"那一类**（见 [`strange_spoon_destination`]）。
pub const STRANGE_SPOON_PERCENT: i32 = 50;''')

    # ── ② 决策函数，挂在 corruption_destination 之后
    patch(PLAY, '''/// §298：这张牌是不是被 `medical_kit` / `blue_candle` **放行**的 `unplayable` 牌''',
                '''/// §302：`strange_spoon` —— 本来要进消耗堆的那张牌，50% 概率改去弃牌堆。
///
/// **只改落区，不改别的任何东西**：不进消耗堆 ⇒ `Exhausted` 通知不发（消耗触发器的
/// 反协同是 wiki 写明的），而"进弃牌堆"也不发丢弃事件（wiki：*"its discard is more similar
/// to the automatic discarding of the player's hand"*）。两件事都是**免费**的 —— 因为落区
/// 本来就是"这张牌最终去哪儿"的唯一答案。
///
/// 边界由调用点决定：只有**真的走完出牌计划**的牌会到这里（见模块头那张表）。
fn strange_spoon_destination(state: &mut CombatState, plan: &PlayPlan<'_>) -> CardZone {
    if plan.destination != CardZone::ExhaustPile {
        return plan.destination;
    }
    // 先读状态再掷骰：`draw_in_range` 要 `&mut`，而状态读的是同一个 `state`。
    let carries = match state.combatant(&plan.source) {
        Some(source) => has_status(source, STRANGE_SPOON_STATUS),
        None => false,
    };
    if !carries {
        return plan.destination;
    }
    // 一次出牌**一次**掷骰（`draw_in_range` 自己推进 `random_step`）。
    if state.draw_in_range(1, 100) <= STRANGE_SPOON_PERCENT {
        CardZone::DiscardPile
    } else {
        CardZone::ExhaustPile
    }
}

/// §298：这张牌是不是被 `medical_kit` / `blue_candle` **放行**的 `unplayable` 牌''')

    # ── ③ 落点：付款成功后解析一次，两个分支都用解析后的值
    patch(PLAY, '''    ensure_affordable(state, &plan.source, &plan.paid)?;
    pay_costs(state, &plan.source, &plan.paid)?;''',
                '''    ensure_affordable(state, &plan.source, &plan.paid)?;
    pay_costs(state, &plan.source, &plan.paid)?;

    // ── §302：**这一张牌最终去哪儿** —— 在这里解析一次（付款之后、节目之前）。
    //
    // 三个理由：① `plan_play` 是纯读，掷骰会污染被拒的出牌；② 付不起的牌没被打出，不该
    // 消耗随机流；③ 下面两条分支（无节目 / 有节目）都必须用**同一个**答案，否则
    // "有节目的牌"和"没节目的牌"会走两条不同的规则。
    let destination = strange_spoon_destination(state, plan);''')

    patch(PLAY, '''        state.enqueue_effect(EffectRequest::MoveCardToZone {
            owner: plan.source,
            card: plan.instance,
            to_zone: plan.destination,
            placement: ZonePlacement::Bottom,
        })?;''',
                '''        state.enqueue_effect(EffectRequest::MoveCardToZone {
            owner: plan.source,
            card: plan.instance,
            to_zone: destination,
            placement: ZonePlacement::Bottom,
        })?;''')

    patch(PLAY, '''    let hook = ProgramTerminalHook::CardPlay {
        player: plan.source,
        card,
        destination: plan.destination,''',
                '''    let hook = ProgramTerminalHook::CardPlay {
        player: plan.source,
        card,
        destination,''')

    # ── ④ 内容：状态载体 + 遗物行
    import json
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    if not any(s['Id'] == 'standard.strange_spoon' for s in doc['Statuses']):
        doc['Statuses'].append({
            'Id': 'standard.strange_spoon',
            'PackageId': 'sts',
            'NameKey': 'Strange Spoon',
            'DescriptionKey': 'Cards which Exhaust when played will instead discard 50% of the time.',
            'Polarity': 'Buff',
            'UsesStacks': True,
            'UsesDuration': False,
            'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance',
            'Tags': ['buff'],
            'PassiveModifiers': [],
            'Triggers': [],
        })
    if not any(r['Id'] == 'strange_spoon' for r in doc['Relics']):
        doc['Relics'].append({'Id': 'strange_spoon', 'DisplayName': 'Strange Spoon',
                              'RunPrograms': None, 'CombatRules': None, 'Rarity': 'Shop'})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

    # ── ⑤ rd-run：遗物 → 开战时的状态载体
    patch(STATE, '''            // §301：`neows_lament` —— 运行层规则（没有内容状态：它不是战斗内的状态）。''',
                '''            // §302：`strange_spoon` —— 战斗内的开关（`plan` 的落区那一格读它）。
            "strange_spoon" => Some(RelicEffect::StartCombatStatus(
                "standard.strange_spoon",
                1,
            )),
            // §301：`neows_lament` —— 运行层规则（没有内容状态：它不是战斗内的状态）。''')
    print('strange_spoon wired')


main()
