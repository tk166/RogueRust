"""§298 A5：`magic_flower`（战斗中治疗 ×150%）+ `medical_kit` / `blue_candle`（放行 unplayable）。

## `magic_flower`

"During combat, healing is 50% more effective." 与 §263 的三个伤害改写同族：
**内核认状态 id，数字是 wiki 的常量**，内容那一行是载体。落点是 `heal_for`（唯一入口）：

```
amount = amount * 150 / 100    // 只在**接受治疗的人**身上有那条状态时
```

⚠️ 乘在 `heal_for` 而不是"每个 `Heal` 请求的入队处"：入队处有七八个（药水、卡牌、
`dealDamageAndHealByLoss`、`Lee's Waffle` ……），一处漏乘就是"某条路的治疗不翻倍"，
而那看起来完全正常。**一个入口一个乘法**。

## `medical_kit` / `blue_candle`

* `medical_kit`：`unplayable` 的 **Status** 牌可以打；
* `blue_candle`：`unplayable` 的 **Curse** 牌可以打，且**每打一张失去 1 点生命**。

内核改一处：`unplayable_validator` 从前只拿 `card`（因此"放行"这件事根本无从判断），
现在拿 `state`，按"牌的种类 + 身上有没有那条状态"决定放不放行。放行之后两张牌的落区
都强制 **`ExhaustPile`**（wiki 两句话都写了 "Exhaust it"）。

`blue_candle` 的"失去 1 点生命"是**内容**：一条 `CardPlayed` 触发器 + `card.hasTag.curse`
的门 + `node.loseHp 1`。所以它不需要动内核 —— 与 §297 的 `strike_dummy` 同一条路。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
RUNSTATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CATALOG = 'D:/Vibe/sts-tui/kernel/rd-core/src/status_catalog.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① `magic_flower`：治疗 ×150%
    patch(EXEC, '''pub const CHEMICAL_X: (&str, i32) = ("standard.chemical_x", 2);''',
                '''pub const CHEMICAL_X: (&str, i32) = ("standard.chemical_x", 2);
/// §298：`magic_flower` —— "During combat, healing is 50% more effective"。
/// 与上面几条同族（内核认状态 id、数字是 wiki 常量），落点是 `heal_for` **唯一**那一处。
pub const MAGIC_FLOWER: (&str, i32) = ("standard.magic_flower", 150);''')

    patch(EXEC, '''fn heal_for(ctx: &mut ExecContext<'_>, target: &CombatantId, amount: i32) -> Result<(), ExecError> {
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;''',
               '''fn heal_for(ctx: &mut ExecContext<'_>, target: &CombatantId, amount: i32) -> Result<(), ExecError> {
    // §298：`magic_flower` —— 接受治疗的人身上有那条状态 ⇒ 治疗 ×150%。
    //
    // ⚠️ 乘在**这一个**函数里，不是每个 `Heal` 请求的入队处：入队处有七八个（药水、卡牌、
    // `dealDamageAndHealByLoss`、事件给的回复……），漏一处就是"某条路的治疗不翻倍"，
    // 而那看起来完全正常。整数乘除（先乘后除）与 wiki 的 "50% more" 一致。
    let amount = if carries_status(ctx.state, target, MAGIC_FLOWER.0) {
        amount.saturating_mul(MAGIC_FLOWER.1) / 100
    } else {
        amount
    };
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;''')

    # ── ② `unplayable` 的放行
    patch(PLAY, '''/// `velvet_choker` 在身上时挂的那条状态（`rd-run` 的开战加成挂它，规则在这里）。
pub const VELVET_CHOKER_STATUS: &str = "standard.velvet_choker";''',
                '''/// `velvet_choker` 在身上时挂的那条状态（`rd-run` 的开战加成挂它，规则在这里）。
pub const VELVET_CHOKER_STATUS: &str = "standard.velvet_choker";
/// §298：`medical_kit` / `blue_candle` —— 放行 `unplayable` 的 Status / Curse 牌。
pub const MEDICAL_KIT_STATUS: &str = "standard.medical_kit";
pub const BLUE_CANDLE_STATUS: &str = "standard.blue_candle";
/// 内容的 `CARD.Tags` 里那三个名字（`status` / `curse` / `unplayable`）。
const STATUS_TAG: &str = "status";
const CURSE_TAG: &str = "curse";''')

    patch(PLAY, '''fn unplayable_validator(card: &CardOnTable<'_>) -> Result<(), PlayError> {
    // §253：`Wish` 那条路会明确越过这一道（请求上的 `ignore_unplayable`）。
    // 其余四道门（stun / 法令 / `PlayCondition` / one_attack）**不受它影响**。
    if card.ignore_unplayable {
        return Ok(());
    }
    if card_has_tag(card.content, card.row, UNPLAYABLE_TAG)? {
        return Err(PlayError::Refused(Refusal::Unplayable));
    }
    Ok(())
}''', '''fn unplayable_validator(
    state: &CombatState,
    card: &CardOnTable<'_>,
) -> Result<(), PlayError> {
    // §253：`Wish` 那条路会明确越过这一道（请求上的 `ignore_unplayable`）。
    // 其余四道门（stun / 法令 / `PlayCondition` / one_attack）**不受它影响**。
    if card.ignore_unplayable {
        return Ok(());
    }
    if !card_has_tag(card.content, card.row, UNPLAYABLE_TAG)? {
        return Ok(());
    }
    // §298：`medical_kit`（Status 牌）与 `blue_candle`（Curse 牌）各自放行**自己那一类**。
    //
    // 为什么按**标签**而不是"稀有度"：内容里这些牌带的是 `status` / `curse` 标签
    // （`wound` / `dazed` / `injury` / `doubt` …），而 `Rarity` 是**奖励池**的桶 ——
    // 两件事在这里恰好同形，但标签才是参考实现读的东西（`card.hasTag.curse` 也用它）。
    let source = source_of(state, &card.source)?;
    if card_has_tag(card.content, card.row, STATUS_TAG)?
        && has_status(source, MEDICAL_KIT_STATUS)
    {
        return Ok(());
    }
    if card_has_tag(card.content, card.row, CURSE_TAG)? && has_status(source, BLUE_CANDLE_STATUS) {
        return Ok(());
    }
    Err(PlayError::Refused(Refusal::Unplayable))
}''')

    patch(PLAY, '''            Validator::Unplayable => unplayable_validator(card),''',
                '''            Validator::Unplayable => unplayable_validator(state, card),''')

    # ── ③ 放行之后：落区强制 `ExhaustPile`
    patch(PLAY, '''    // ── 落点（`:298-302`）：法令 `PlayedCardsExhaust` 已被上面那道闸门否决，
    // 所以这里只剩卡定义自己的 `PlayedCardDestinationZone`。
    let destination = match req.override_destination {
        Some(zone) => zone,''', '''    // ── 落点（`:298-302`）：法令 `PlayedCardsExhaust` 已被上面那道闸门否决，
    // 所以这里只剩卡定义自己的 `PlayedCardDestinationZone`。
    let destination = match req.override_destination {
        Some(zone) => zone,
        // §298：`medical_kit` / `blue_candle` 放行的那张牌**必然消耗**（wiki 两句话都写了
        // "Exhaust it"）。否则"打一张 wound"会把它塞进弃牌堆 —— 玩家能反复打同一张，
        // 与 wiki 的"打掉就没了"相反，而且没有任何东西会红。
        None if unplayable_is_free(state, &card)? => CardZone::ExhaustPile,''')

    patch(PLAY, '''/// 每一张牌**自己的**落区（`PlayedCardDestinationZone`）。''',
                '''/// §298：这张牌是不是被 `medical_kit` / `blue_candle` **放行**的 `unplayable` 牌
/// （放行的那一类 ⇒ 落区强制 `ExhaustPile`）。
fn unplayable_is_free(state: &CombatState, card: &CardOnTable<'_>) -> Result<bool, PlayError> {
    if !card_has_tag(card.content, card.row, UNPLAYABLE_TAG)? {
        return Ok(false);
    }
    let source = source_of(state, &card.source)?;
    if card_has_tag(card.content, card.row, STATUS_TAG)? && has_status(source, MEDICAL_KIT_STATUS) {
        return Ok(true);
    }
    if card_has_tag(card.content, card.row, CURSE_TAG)? && has_status(source, BLUE_CANDLE_STATUS) {
        return Ok(true);
    }
    Ok(false)
}

/// 每一张牌**自己的**落区（`PlayedCardDestinationZone`）。''')
    print('kernel: magic_flower + unplayable 放行')


main()
