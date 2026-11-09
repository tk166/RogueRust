"""§311（六）：**同一只怪物的多个实例** —— 起始状态挂错人的那个 bug。

把 `enc_byrds` 修成三只之后，`flying_halves_attack_damage_and_loses_a_stack_per_hit` 当场红：
读到的 Flying 是 **8 层**（= 3 × 3 − 1），而不是 2。

根因：构建战斗时每个实例的战斗员 id 是 `byrd` / `byrd#2` / `byrd#3`，而
`apply_starting_statuses` 用的是**plain id**（`CombatantId::new(id)`）—— 于是三份
`StartingStatuses` 全叠到第一只身上（3+3+3=9），另外两只**一层都没有**。

同一个 bug 早就存在：`enc_three_sentries` 是三只哨卫，每只 `Artifact 1` —— 实际是
sentry_1 身上 3 层、另外两只 0 层。三只 byrd 只是把它暴露出来的那一面。

修法：把"实例 id 怎么算"抽成**一个**函数，构建方与挂状态方都用它（否则同一个 `#n` 规则
写在两处，一定会漂）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


HELPER = '''/// 一个敌人实例的战斗员 id：第一次是 `id`，重复的加 `#2` / `#3` ……
///
/// §311：这条规则**只有一处**。构建战斗（`PlanCombatant.id`）与挂起始状态
/// （[`apply_starting_statuses`]）都必须用它 —— 旧实现里后者拿的是 **plain** id，于是
/// "三只 byrd"的三份 `StartingStatuses` 全叠到第一只身上（实测 9 层 Flying 在 `byrd` 上、
/// 另外两只 0 层；`enc_three_sentries` 的 Artifact 同样是 3 层叠在一只身上）。
fn unique_instance_id(id: &'static str, seen: &mut Vec<&'static str>) -> &'static str {
    let unique: &'static str = if seen.contains(&id) {
        let mut count = 2usize;
        let mut text = std::format!("{id}#{count}");
        while seen.iter().any(|entry| *entry == text.as_str()) {
            count += 1;
            text = std::format!("{id}#{count}");
        }
        Box::leak(text.into_boxed_str())
    } else {
        id
    };
    seen.push(unique);
    unique
}

'''


def main():
    # 1. 帮助函数放在 `apply_starting_statuses` 之前。
    anchor = '''/// Put every enemy's `StartingStatuses` onto it (§175b).'''
    patch(anchor, HELPER + anchor)

    # 2. 构建方：改用共享的规则。
    patch('''        // The id this combatant will actually carry: `id` the first time, `id#2`, `id#3` after that.
        let unique: &'static str = if seen_ids.contains(&id) {
            let mut count = 2usize;
            let mut text = std::format!("{id}#{count}");
            while seen_ids.iter().any(|seen| *seen == text.as_str()) {
                count += 1;
                text = std::format!("{id}#{count}");
            }
            Box::leak(text.into_boxed_str())
        } else {
            id
        };
        seen_ids.push(unique);''',
'''        // The id this combatant will actually carry (`id` / `id#2` / …). §311: the rule lives in
        // **one** function because the starting-status pass needs the same answer.
        let unique: &'static str = unique_instance_id(id, &mut seen_ids);''')

    # 3. 挂状态方：同样用共享规则，并且跳过 `Spawn: false`（与构建方同一顺序）。
    patch('''        let id = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;
        let Ok(target) = rd_core::state::CombatantId::new(id) else {
            return Err(format!("`{id}` is not a usable combatant id"));
        };''',
'''        let id = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;
        // §195.6/§311: 与构建方**同一条顺序**：`Spawn: false` 的占位记录不生成实例，
        // 因此也不消耗一个 `#n`。
        if !spec
            .spawn()
            .map_err(|e| format!("ENCT enemy Spawn: {}", detail(&e)))?
        {
            continue;
        }
        let unique = unique_instance_id(id, &mut seen);
        let Ok(target) = rd_core::state::CombatantId::new(unique) else {
            return Err(format!("`{unique}` is not a usable combatant id"));
        };''')

    # 4. `apply_starting_statuses` 需要自己的 `seen`（与构建方的循环同序）。
    patch('''    for (slot, spec) in enemies.iter().enumerate() {
        let mut spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;''',
'''    let mut seen: Vec<&'static str> = Vec::new();
    for (slot, spec) in enemies.iter().enumerate() {
        let mut spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;''')
    print('instance-id fix applied')


main()
