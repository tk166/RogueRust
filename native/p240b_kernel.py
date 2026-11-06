"""§240 内核（下）：随机造牌的实体 + 印刷费用的唯一读者。"""
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


# ---------------------------------------------------------------- play.rs：印刷费用的唯一读者
patch('play.rs', [
    ('''fn calculate_costs(state: &CombatState, card: &CardOnTable<'_>) -> Result<PaidCosts, PlayError> {''',
     '''/// §240：**一张定义的能量印刷费用**（每副本价格用得上它）。
///
/// `Infernal Blade` 造出来的牌"本回合费用为 0" = 给它一个 `-印刷费用` 的每副本价格（§161.4）。
/// 这个数字必须与 `calculate_costs` 同源 —— 两个读者各读一遍 `Costs` 列表迟早会漂
/// （§4.20），所以这里**构造一个 `CardOnTable` 直接问 `calculate_costs`**。
///
/// 返回 `None` 的两种情形：定义不在卡表里，或者它是 **X 费牌**（那种牌没有"印刷费用"这个数，
/// 它的费用是出牌那一刻的全部能量）。调用方（随机池）据此把 X 费牌排除掉。
#[must_use]
pub(crate) fn printed_energy_cost(
    content: &Content<'_>,
    definition: &str,
    source: CombatantId,
) -> Option<i32> {
    let entry = content.lookup_in(definition, EK_CARD)?;
    let row = content.card(u32::from(entry.index))?;
    let is_x_cost = card_has_tag(content, row, X_COST_TAG).unwrap_or(false);
    if is_x_cost {
        return None;
    }
    let card = CardOnTable {
        content,
        row,
        source,
        instance: CardInstanceId::new(definition).ok()?,
        target: None,
        is_action: false,
        is_attack: false,
        is_skill: false,
        is_x_cost,
    };
    // `calculate_costs` 不会对非 X 费牌读状态里任何东西（它只走 `Costs` 列表 + 每副本价格，
    // 而一张刚落地的牌没有那个计数器），所以这里不需要真的 `CombatState`。
    let state = CombatState::new(crate::state::CombatId::new("cost").ok()?, 0);
    let paid = calculate_costs(&state, &card).ok()?;
    let energy = crate::state::ResourceId::new("standard.energy").ok()?;
    Some(paid.amount_for(&energy).unwrap_or(0))
}

fn calculate_costs(state: &CombatState, card: &CardOnTable<'_>) -> Result<PaidCosts, PlayError> {'''),
])
print('done')
