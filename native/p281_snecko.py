"""§281：Snecko Oil 的价格随机化改走 `CombatState::draw_in_range`，范围改由**内容**给。

原实现（`rd-wasm`）：

    let mut seed = session.state.random_seed as u32;
    let roll = rd_core::rng::next_u32(&mut seed) % 4;
    session.state.random_seed = seed as i32;
    session.state.random_step = session.state.random_step.saturating_add(1);

两处问题：
* `random_seed` 被写回 —— 洗牌那条路只推 step，于是两条路对"下一个随机数"的看法分家；
* `0..=3` 硬编码在 wasm 里，注释自己写着"wiki 没给范围，StS 用 0-3"。范围是**内容**的属性
  （`combat_randomize_costs:0:3`），放在这里就等于内核替内容做了决定。

改完之后：范围在内容里，抽取走唯一入口，step 每次恰好 +1。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
C = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 从原子串里读范围（`combat_randomize_costs:0:3`），缺省 0..=3。
    old_head = '''        "combat_randomize_costs" => {
            // Snecko Oil, part 2. Part 1 is the `combat_draw` atom next to it in the content
            // (`Effect: "combat_draw,combat_randomize_costs"`).
            //
            // The draw is `amount` (5); the randomized price is **0..=3** -- that is the whole
            // content of this rule, so it is a constant here rather than a field nobody could
            // source from the wiki ("Randomize the costs" gives no range; StS uses 0-3).'''
    new_head = '''        "combat_randomize_costs" => {
            // Snecko Oil, part 2. Part 1 is the `combat_draw` atom next to it in the content
            // (`Effect: "combat_draw,combat_randomize_costs:0:3"`).
            //
            // The draw is `amount` (5); the randomized price range comes from the **atom
            // payload** (§281). Before that the range was a constant here, with a comment that
            // admitted it: "the wiki gives no range; StS uses 0-3". A range is a **content**
            // property -- the kernel deciding it means every future potion with a different
            // range would need an edit here.
            let (min_cost, max_cost) = cost_range(atom_payload);'''
    s = patch(s, old_head, new_head)

    # ② 换成唯一入口
    old_roll = '''            for slot in &slots[..count] {
                // One draw per card, each advancing `random_step` by one -- the same convention the
                // shuffle uses (`state.rs`: "洗完之后 `random_step += 1`"), so a replay of the same
                // seed randomizes the same ways.
                let mut seed = session.state.random_seed as u32;
                let roll = rd_core::rng::next_u32(&mut seed) % 4;
                session.state.random_seed = seed as i32;
                session.state.random_step = session.state.random_step.saturating_add(1);
                if let Some(card) ='''
    new_roll = '''            for slot in &slots[..count] {
                // §281：**一次**抽取，走 `CombatState::draw_in_range`（战斗随机流的唯一入口）。
                // 老实现手抄了 `next_u32` 并**同时**写回 `random_seed`，于是与洗牌那条路
                // 对"下一个随机数"的看法分家 —— 而症状是"同种子两次跑出不同牌序"。
                let roll = session.state.draw_in_range(min_cost, max_cost);
                if let Some(card) ='''
    s = patch(s, old_roll, new_roll)

    # ③ 助手：解析锚点 payload
    s = patch(s, '''/// Is this potion atom about a **fight**? (§158)''',
'''/// §281：`combat_randomize_costs:0:3` 的**范围**（`min:max`，两端都含）。
///
/// 缺省 `0..=3` 是 StS 的实际范围（wiki 只说 "Randomize the costs"）—— 但缺省只用于
/// **旧内容**：新内容应当写清楚，而内容门会要求它写。
fn cost_range(payload: Option<&str>) -> (i32, i32) {
    let Some(payload) = payload else {
        return (0, 3);
    };
    let mut parts = payload.split(':');
    let (Some(min), Some(max), None) = (parts.next(), parts.next(), parts.next()) else {
        return (0, 3);
    };
    match (min.parse::<i32>(), max.parse::<i32>()) {
        (Ok(min), Ok(max)) if 0 <= min && min <= max => (min, max),
        _ => (0, 3),
    }
}

/// Is this potion atom about a **fight**? (§158)''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('snecko oil -> draw_in_range + content range')
    print('NEXT: 需要把 `atom_payload` 与 match 的绑定接上（编译错误会指出来）')


main()
