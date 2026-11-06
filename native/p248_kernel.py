"""§248 内核：费用修饰器三件套（"设绝对值 / 按印刷费用取 min / 随机取一张手牌"）。

§247 被挡回的原因是**语义**：`Enlightenment` 是 `min(cost, 1)`，而 `set 1` 会把 0 费牌抬成 1。
要写对它只有一条路：**知道印刷费用**。所以这一节先补三块，全是通用件：

1. `play::printed_energy_cost` —— **印刷费用的唯一读者**（内部调 `calculate_costs`，
   不是把 `Costs` 列表再解析一遍。§240 我删过一份"第二读者"，这次不再造第二份）。
2. `addCardCounter.Mode` —— `Add`（缺席，既有行为）/ `Set`（覆盖）/ **`SetMin`**
   （只在印刷费用**更高**时下调；`min` 与 `set` 的差别正是 §247 那个 0 费牌的坑）。
3. `forEachCardInZone.Order` —— `"Random"`（洗一遍再 `TakeFirst`）。`Madness` 要"手里**随机一张**"，
   而现在只有按牌堆序的 `TakeFirst`。
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


# ============================================================ play.rs：印刷费用的唯一读者
patch('play.rs', [
    ('''fn calculate_costs(state: &CombatState, card: &CardOnTable<'_>) -> Result<PaidCosts, PlayError> {''',
     '''/// §248：**一张定义的印刷能量费用**（"按印刷费用决定"的那些卡要用它）。
///
/// 实现上直接问 [`calculate_costs`]：**只有一个读者**。§240 曾写过一份"再解析一遍 `Costs`"的
/// 版本（为了算 `-印刷费用` 的 delta），那是第二份认识 —— 那时候删掉是对的（绝对价够了）。
/// 现在 `Enlightenment` 的 `min(cost, 1)` **必须**知道印刷费用，所以把它加回来，
/// 但这次走既有那条路，不再复制解析逻辑。
///
/// 返回 `None`：定义不在卡表里，或者它是 **X 费牌**（那种牌没有"印刷费用"这个数）。
#[must_use]
pub(crate) fn printed_energy_cost(
    content: &Content<'_>,
    definition: &str,
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
        source: CombatantId::EMPTY,
        instance: CardInstanceId::new(definition).ok()?,
        target: None,
        is_action: false,
        is_attack: false,
        is_skill: false,
        is_x_cost,
    };
    // 非 X 费牌的 `calculate_costs` 只读 `Costs` 列表与每副本价格（新牌还没有那个计数器），
    // 所以这里不需要真实状态。**这张牌当时的状态无关紧要**：问的是"印刷"价。
    let state = CombatState::new(crate::state::CombatId::new("print").ok()?, 0);
    let paid = calculate_costs(&state, &card).ok()?;
    let energy = crate::state::ResourceId::new("standard.energy").ok()?;
    Some(paid.amount_for(&energy).unwrap_or(0))
}

fn calculate_costs(state: &CombatState, card: &CardOnTable<'_>) -> Result<PaidCosts, PlayError> {'''),
])

# ============================================================ exec.rs：Mode + Order
patch('exec.rs', [
    ('''    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, current.saturating_add(delta))?;
    }''',
     '''    // §248：`Mode` —— `Add`（缺席）/ `Set`（覆盖）/ `SetMin`（**只在印刷费用更高时下调**）。
    //
    // `SetMin` 与 `Set` 的差别就是 §247 那个坑：`Enlightenment` 是 "reduce **to** 1"，
    // 对一张 0 费牌它什么也不该做；而 `Set` 会把 0 写成 1，把免费牌变成收费牌。
    let value = match node.str_field("Mode")? {
        None | Some("Add") => current.saturating_add(delta),
        Some("Set") => delta,
        Some("SetMin") => {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let Some(card) = ctx.state.card(card_slot) else {
                return resume_later(ctx.state, frame, slot);
            };
            let definition = card.definition_id;
            match crate::play::printed_energy_cost(content, definition.as_str()) {
                // 印刷费用已经不高 ⇒ 不动（"min" 的那一半）。
                Some(printed) if printed <= delta => current,
                // 印刷费用更高 ⇒ 下调到 `delta`。
                Some(_) => delta,
                // X 费牌没有印刷费用这个数 —— 响亮失败（内容不该对它们用它）。
                None => return Err(ExecError::Ir(IrError::Missing("printed cost"))),
            }
        }
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, value)?;
    }'''),
    ('''    let take_first = node.int_field("TakeFirst")?;''',
     '''    let take_first = node.int_field("TakeFirst")?;
    // §248：`Order: "Random"` —— 洗一遍快照再取。`Madness` 要"手里**随机一张**"，
    // 而 `TakeFirst` 只按牌堆序取（那会让"随机"变成"总是第一张"，而且看起来完全正常）。
    let random_order = match node.str_field("Order")? {
        None => false,
        Some("Random") => true,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };'''),
])

s = io.open(K + 'exec.rs', encoding='utf-8').read()
# 在 TakeFirst 截断之前打乱
old = '''    // ── `:463-464`：`Enumerable.Take(n)`。`n <= 0` ⇒ 空序列（**不是**截成 1，**不是**错误）。'''
new = '''    // §248：`Order: "Random"` ⇒ 先把候选洗一遍（一次抽签，与洗牌同一本 `random_step` 账）。
    if random_order {
        shuffle_candidates(&mut slots[..count], ctx);
    }

    // ── `:463-464`：`Enumerable.Take(n)`。`n <= 0` ⇒ 空序列（**不是**截成 1，**不是**错误）。'''
assert s.count(old) == 1
io.open(K + 'exec.rs', 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))
print('patched exec.rs (Order)')
print('done')
