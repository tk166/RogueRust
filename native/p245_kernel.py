"""§245 内核：`Panic Button` 的那条"不能从牌里获得格挡"。

wiki：`Gain (30;40) Block. You cannot gain Block **from cards** for 2 turns. Exhaust.`

关键在 "**from cards**"：遗物/状态（如 Metallicize）给的格挡**照样有效**。内核里"这一次是谁在给格挡"
只有一个可靠判据 —— `ctx.resolving_card`（正在结算那张牌的节目里它非空，状态/遗物/敌人招式的节目里
它是 `None`）。所以规则写成：

> 目标身上有 `standard.no_block_from_cards` **且** 这次格挡来自一张牌 ⇒ 格挡量归 0。

这比"有状态就不给格挡"窄，比"不管来源"准 —— 后者会把 Metallicize 一起打死，而那在页面上
看起来完全正常（玩家只会觉得"我的金属化不工作了"）。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


patch('exec.rs', [
    ('''fn gain_block_for(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    amount: i32,
) -> Result<(), ExecError> {
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;''',
     '''/// §245：`Panic Button` —— "You cannot gain Block **from cards** for 2 turns"。
///
/// 判据用 `ctx.resolving_card`："这一次格挡是不是一张牌给的"。它是内核里唯一回答这个问题的东西
/// （状态/遗物/敌人招式的节目里它是 `None`）。
///
/// 只归 0，**不报错**：`Panic Button` 那条牌自己的 `gainBlock` 也走这里，而它先给格挡、后挂状态
/// （队列顺序），所以正常出牌时这条规则不生效；只有"状态已经在身上"时才拦。
fn cards_cannot_give_block(ctx: &ExecContext<'_>, target: &CombatantId) -> bool {
    if ctx.resolving_card.is_none() {
        return false;
    }
    ctx.state.combatant(target).is_some_and(|combatant| {
        combatant
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == NO_BLOCK_FROM_CARDS_STATUS)
    })
}

/// §245：`standard.no_block_from_cards`（`Panic Button`）。
const NO_BLOCK_FROM_CARDS_STATUS: &str = "standard.no_block_from_cards";

fn gain_block_for(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    amount: i32,
) -> Result<(), ExecError> {
    // §245：`Panic Button` 的"2 回合内不能从牌里获得格挡"。放在**最前面**：早点返回，
    // 后面那串修饰器/容量记账一步都不该动（"拒绝 ⇒ 一个字节都不改"）。
    if cards_cannot_give_block(ctx, target) {
        return Ok(());
    }
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;'''),
])
print('done')
