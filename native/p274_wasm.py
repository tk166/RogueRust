"""§274 第四批：三个 wasm 导出（拾取队列）+ `rd_run_event_needs` 的穷尽映射。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


EXPORTS = '''/// §274：还欠几次"拾取时的牌组编辑"（`0` = 不欠，`-1` = 没有一局）。
///
/// 与 `rd_run_event_needs` 是**两件事**：那个是"事件问句"（走 `Pending::EventCard`），
/// 这个是"遗物问句"（不走 `pending`），所以它可以和奖励屏、宝箱屏**同时**存在 ——
/// 这正是打完 Boss 拿 Boss 遗物、还想接着拿卡牌奖励那条路径需要的。
#[no_mangle]
pub extern "C" fn rd_run_pickup_picks() -> i32 {
    run_slot().as_ref().map_or(-1, |run| i32::from(run.state.pickup_picks()))
}

/// §274：欠的是哪一种编辑：`0` 不欠、`1` 移除、`2` 升级、`3` 改造、`4` 改造并升级、`-1` 没有一局。
#[no_mangle]
pub extern "C" fn rd_run_pickup_change() -> i32 {
    use rd_run::state::DeckChange;
    let Some(run) = run_slot().as_ref() else {
        return -1;
    };
    match run.state.pickup_change() {
        None => 0,
        Some(DeckChange::Remove) => 1,
        Some(DeckChange::Upgrade) => 2,
        Some(DeckChange::Transform) => 3,
        Some(DeckChange::TransformAndUpgrade) => 4,
    }
}

/// §274：兑现一次拾取时的牌组编辑（牌组下标 `index`）。
#[no_mangle]
pub extern "C" fn rd_run_pickup_card(index: i32) -> i32 {
    if index < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_EVENT_CARD, index, -1, "");
    let pool = match full_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .pickup_card(index as usize, &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 新导出（放在 rd_run_pick_event_card 之后）
    src = patch(src, "/// The open event's choices, from the content.", EXPORTS + "/// The open event's choices, from the content.", 'exports')

    # ② `rd_run_event_needs` 的穷尽映射
    src = patch(src, '''    match session.state.event_follow_up() {
        Some(DeckChange::Remove) => 1,
        Some(DeckChange::Upgrade) => 2,
        Some(DeckChange::Transform) => 3,
        None => 0,
    }''',
                '''    match session.state.event_follow_up() {
        Some(DeckChange::Remove) => 1,
        Some(DeckChange::Upgrade) => 2,
        Some(DeckChange::Transform) => 3,
        // §274：`astrolabe` 会用到它，但事件从不用它 —— 给一个明确的值而不是 panic。
        Some(DeckChange::TransformAndUpgrade) => 4,
        None => 0,
    }''', 'event needs')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('wasm: pickup exports')


main()
