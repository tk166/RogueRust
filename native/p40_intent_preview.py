"""§386：意图预览要能读**掷骰值**（虱子的 Bite / Curl Up 都是 `combatantCounter`）。

## 玩家报的

"攻击 curl_up 的数值是零似乎不对"。

## 根因（不是内容，是预览）

`louse_green.bite` 的伤害是 `dealDamage{ Amount: combatantCounter(source, "roll.bite") }`
—— 值在**开战时掷**（5–7，A2 起 6–8；内容里 `enc_*louse*` 的每个敌人条目都声明了）。

而 `program_damage`（`rd-wasm` 的意图预览）只认**字面量**：
`if amount.kind_str() != Ok("const") { return false }` ⇒ 整个意图答 `-1`
⇒ 界面上"攻击"后面没有数字（玩家读成 0）。Curl Up 的格挡同理（`roll.curl_up`）。

⚠️ 这条**不能**改成"猜一个中位数"：玩家要靠这个数字决定打不打。
所以修法是**真的求值**：把 `combatantCounter` / `combatantStatusStacks` 这两种
"读某个战斗员身上的数"的表达式解出来（它们只需要状态，不需要掷骰）。

## 判据

* 掷骰值在范围内 ⇒ 预览给的是**那个值**（不是 -1、不是中位数）；
* 仍然解不出来的表达式（`multiply` 套状态修饰等）⇒ 依然 `-1`，界面上**不显示数字**，
  而不是显示 0（"不猜"这条纪律没变）。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''fn program_damage(content: &'static Content<'static>, action_row: u32) -> i32 {
    let Ok(root) = enemy_action_program_root(content, action_row) else {
        return -1;
    };
    let mut total = 0i32;
    if !walk_damage(root, 0, &mut total) {
        return -1;
    }
    total
}

/// Depth-first walk behind [`program_damage`]; `false` = "cannot be answered statically".
fn walk_damage(node: NodeRef<'static>, depth: usize, total: &mut i32) -> bool {
    if depth > MAX_PREVIEW_DEPTH {
        return false;
    }
    let Ok(kind) = node.kind_str() else {
        return false;
    };
    match kind {
        "node.dealDamage" => {
            let Some(amount) = node.node_field("Amount").ok().flatten() else {
                return false;
            };
            if amount.kind_str() != Ok("const") {
                return false; // 依赖状态 ⇒ 不猜
            }
            let Ok(Some(value)) = amount.int_field("Value") else {
                return false;
            };
            *total = total.saturating_add(value);
            true
        }'''

NEW = '''fn program_damage(content: &'static Content<'static>, action_row: u32) -> i32 {
    let Ok(root) = enemy_action_program_root(content, action_row) else {
        return -1;
    };
    let mut total = 0i32;
    if !walk_damage(root, 0, &mut total, None) {
        return -1;
    }
    total
}

/// §386：**带状态**的版本 —— 掷骰值（`combatantCounter`）能解出来了。
///
/// 为什么不复用 [`program_damage`]：那一条是"只看程序文本"的纯函数（`--enemies` 的
/// 对拍与闸门都用它），加上状态就成了另一个东西。两条并存，调用方按需要选。
fn program_damage_with_state(
    content: &'static Content<'static>,
    action_row: u32,
    state: &rd_core::state::CombatState,
    actor: &rd_core::state::CombatantId,
) -> i32 {
    let Ok(root) = enemy_action_program_root(content, action_row) else {
        return -1;
    };
    let mut total = 0i32;
    if !walk_damage(root, 0, &mut total, Some((state, actor))) {
        return -1;
    }
    total
}

/// Depth-first walk behind [`program_damage`]; `false` = "cannot be answered statically".
///
/// §386：`state` 给了就能解 `combatantCounter` / `combatantStatusStacks`
/// （虱子的 `roll.bite` 就挂在这两种上面）。**仍然解不出来的照旧答 `false`** ——
/// 猜一个数字比不显示更糟：玩家会拿它做决策。
fn walk_damage(
    node: NodeRef<'static>,
    depth: usize,
    total: &mut i32,
    state: Option<(&rd_core::state::CombatState, &rd_core::state::CombatantId)>,
) -> bool {
    if depth > MAX_PREVIEW_DEPTH {
        return false;
    }
    let Ok(kind) = node.kind_str() else {
        return false;
    };
    match kind {
        "node.dealDamage" => {
            let Some(amount) = node.node_field("Amount").ok().flatten() else {
                return false;
            };
            let value = match amount.kind_str() {
                Ok("const") => match amount.int_field("Value") {
                    Ok(Some(value)) => value,
                    _ => return false,
                },
                // §386：掷骰值。`Selector` 现在只有 `sel.source`（虱子的 Bite 就是自己身上的
                // `roll.bite`）；别的选择器仍然答"解不出来"，不猜。
                Ok("combatantCounter") => match state {
                    Some((state, actor)) => match counter_of(amount, state, actor) {
                        Some(value) => value,
                        None => return false,
                    },
                    None => return false,
                },
                Ok("combatantStatusStacks") => match state {
                    Some((state, actor)) => match stacks_of(amount, state, actor) {
                        Some(value) => value,
                        None => return false,
                    },
                    None => return false,
                },
                _ => return false,
            };
            *total = total.saturating_add(value);
            true
        }'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# 递归调用补一个参数
OLD2 = '''            for id in ids.iter().take(count) {
                if !walk_damage(node.child(*id), depth + 1, total) {
                    return false;
                }
            }'''
NEW2 = '''            for id in ids.iter().take(count) {
                if !walk_damage(node.child(*id), depth + 1, total, state) {
                    return false;
                }
            }'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

# 两个小工具：从表达式里读 CounterId / StatusId，并只接受 `sel.source`
OLD3 = '''/// Depth-first walk behind [`program_damage`]; `false` = "cannot be answered statically".'''
NEW3 = '''/// `combatantCounter{Selector, CounterId}` → 那个战斗员身上同名计数器的值。
///
/// ⚠️ 只认 `sel.source`：预览是"这个敌人要做什么"，读别人的数需要更多上下文
/// （目标、事件参数），猜错的方向是"显示一个不是自己的数"。解不出 ⇒ `None`（调用方答 -1）。
fn counter_of(
    node: NodeRef<'static>,
    state: &rd_core::state::CombatState,
    actor: &rd_core::state::CombatantId,
) -> Option<i32> {
    if !selector_is_source(node.node_field("Selector").ok().flatten()?) {
        return None;
    }
    let key = node.str_field("CounterId").ok().flatten()?;
    let key = rd_core::state::CounterId::new(key).ok()?;
    let combatant = state.combatant(actor)?;
    combatant
        .counters()
        .iter()
        .find(|counter| counter.key == key)
        .map(|counter| counter.value)
}

/// `combatantStatusStacks{Selector, StatusId}` → 那个战斗员身上同名状态的层数。
fn stacks_of(
    node: NodeRef<'static>,
    state: &rd_core::state::CombatState,
    actor: &rd_core::state::CombatantId,
) -> Option<i32> {
    if !selector_is_source(node.node_field("Selector").ok().flatten()?) {
        return None;
    }
    let id = node.str_field("StatusId").ok().flatten()?;
    let combatant = state.combatant(actor)?;
    combatant
        .statuses()
        .iter()
        .find(|status| status.definition_id.as_str() == id)
        .map(|status| status.stacks)
}

/// 这个选择器是不是"出手者自己"（`sel.source`）。
fn selector_is_source(selector: NodeRef<'static>) -> bool {
    selector.kind_str() == Ok("sel.source")
}

/// Depth-first walk behind [`program_damage`]; `false` = "cannot be answered statically".'''
assert t.count(OLD3) == 1
t = t.replace(OLD3, NEW3, 1)

# 调用点：用带状态的版本
OLD4 = '''                    let damage = program_damage(content, choice.action_row);'''
NEW4 = '''                    // §386：带状态求值 —— 掷骰伤害（`roll.bite`）才显示得出来。
                    let damage =
                        program_damage_with_state(content, choice.action_row, &self.state, &id);'''
assert t.count(OLD4) == 1
t = t.replace(OLD4, NEW4)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('program_damage_with_state + counter/status 求值')
