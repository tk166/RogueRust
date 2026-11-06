"""§247 内核：`zoneCount` 表达式 + `addCardCounter.Mode: Set`。

1. **`combatantZoneCount{Selector, Zone}`**（INT）—— `Mind Blast` 的"按抽牌堆张数打伤害"。
   在此之前内核能数**手牌**（`hand.hasCardWithTag` 那条 bool、以及 §239 的 `handIsAllAttacks`），
   但**没有任何表达式能数一个牌区有几张**。
2. **`addCardCounter.Mode`** —— `Enlightenment` 要"把手里每张牌的价格**设**成 1"。
   原来的节点只会 `current + delta`（累加），而"设"与"加"在费用上是两件事：
   `card_cost_override` 是一个**绝对值**，累加两次会把 0 变成 2。

⚠️ 两条都只在**内容点名时**生效：`Mode` 缺席 = `Add`（既有 3 张牌的行为一字不变），
`zoneCount` 是一个新 kind（没有内容用就没人走）。
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


# ---------------------------------------------------------------- expr.rs：zoneCount
patch('expr.rs', [
    ('''    // §229：正在结算的那份副本的 mark counter（`Rampage` 的 "increase **this card's** damage"）。
    "card.counter",
];''',
     '''    // §229：正在结算的那份副本的 mark counter（`Rampage` 的 "increase **this card's** damage"）。
    "card.counter",
    // §247：**一个牌区里现在有几张牌**（`Mind Blast` 的"按抽牌堆张数打伤害"）。
    //
    // 字段照 `combatantStatusStacks` 的形状：`Selector`（谁）+ `Zone`（哪个区，牌区枚举名）。
    // 不认识的区名 ⇒ `Missing("Zone")`，绝不"当成 0"—— 0 是一个**合法**答案（空牌区），
    // 拼错的区名与"空牌区"必须分得开。
    "combatantZoneCount",
];'''),
    ('''        // §229: the mark counter of **this copy**.''',
     '''        // §247: how many cards are in a zone right now (Mind Blast).
        "combatantZoneCount" => {
            let zone_name = node.str_field("Zone")?.ok_or(IrError::Missing("Zone"))?;
            let zone = crate::exec::zone_from_wire_name(zone_name)
                .ok_or(IrError::Missing("Zone"))?;
            // 单目标读（与 `currentHealth`/`maxHealth` 同一个帮手）：一个牌区的张数是"那个人的"，
            // 而多目标对"张数"没有良定义的答案（是加起来还是取一个？）—— 与那两个 kind 同一条裁决。
            let Some(owner) = read_single_target(node, ctx)? else {
                return Ok(0);
            };
            let cards = ctx.state.card_zones(&owner).map_or(0, |zones| zones.count(zone));
            Ok(i32::try_from(cards).unwrap_or(i32::MAX))
        }

        // §229: the mark counter of **this copy**.'''),
])

# ---------------------------------------------------------------- exec.rs：名字解析器 + Mode: Set
patch('exec.rs', [
    ('''fn add_card_counter_node(''',
     '''fn add_card_counter_node('''),
    ('''    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, current.saturating_add(delta))?;
    }''',
     '''    // §247：`Mode: "Set"` = **覆盖**（`Enlightenment` 的"把价格设成 1"）。
    // 缺席 = `Add`（既有内容的行为一字不变）。
    let mode = node.str_field("Mode")?;
    let value = match mode {
        None | Some("Add") => current.saturating_add(delta),
        Some("Set") => delta,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, value)?;
    }'''),
])
print('done')
