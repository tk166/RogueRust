"""§286 wasm：把 `EventMove`（分支表 / 进入效果 / 战斗档位）装好递下去。

进入效果的**目标段**不止一个了（分支表最多四条），所以这里按目标 id 建一张小表：
每个目标段读一次 `entry_at(level)`，最多 4 条效果。运行层只按**最终落点**查一次。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ── ① 掷骰 → 分支表 + 进入效果 + 战斗
    s = patch(s, '''    // §278：这一段选完之后还去不去下一段，**由内容**说（`option.Next`）。
    let next = choice.goes_on();
    // §285：`Chance`/`NextFail` 都在选项上 —— **掷骰在运行层**（`RunStream::Event`），
    // 这里只把两个目标和概率递过去。
    let roll = choice
        .roll
        .map(|(chance, on_fail)| rd_run::state::EventRoll {
            chance,
            on_success: next.unwrap_or(""),
            on_fail,
        });
    let outcome = session
        .state
        .resolve_event_effects(&parsed[..specs.len()], next, roll, &pool)
        .map(|_| 0i32);''',
'''    // §278：这一段选完之后还去不去下一段，**由内容**说（`option.Next`）。
    let next = choice.goes_on();
    // §286：**权重分支**在选项上、**掷骰在运行层**（`RunStream::Event`）—— 这里只把表和目标
    // 段递过去。A15 那一版优先（`Dead Adventurer` 的伏击率 25% → 35%）。
    let branches = choice.branches_at(level, rd_run::state::A_EVENTS_WORSE);
    // §286：**目标段的进入效果**。目标可能是 `next`，也可能是分支表里的任何一个 —— 所以按
    // 目标 id 建一张小表（最多 4 个目标），运行层只按最终落点查一次。
    //
    // 布局：`entry_pool[i]` 是第 `i` 个目标段的效果数组，`entry_pairs` 把 id 与切片配起来。
    let mut entry_pool: [[(rd_run::state::EventEffect, Option<&'static str>);
                          rd_run::state::MAX_EVENT_EFFECTS]; rd_run::state::MAX_EVENT_BRANCHES] =
        [[(rd_run::state::EventEffect::Nothing, None); rd_run::state::MAX_EVENT_EFFECTS];
         rd_run::state::MAX_EVENT_BRANCHES];
    let mut entry_len = [0usize; rd_run::state::MAX_EVENT_BRANCHES];
    let mut entry_ids: [&'static str; rd_run::state::MAX_EVENT_BRANCHES] =
        [""; rd_run::state::MAX_EVENT_BRANCHES];
    let mut entry_count = 0usize;
    {
        let content = content();
        // 候选目标：`next` 与每条分支的落点（重复的只算一次）。
        let mut targets: [&'static str; 1 + rd_run::state::MAX_EVENT_BRANCHES] =
            [""; 1 + rd_run::state::MAX_EVENT_BRANCHES];
        let mut target_count = 0usize;
        if let Some(next) = next {
            // `goes_on()` 借的是内容里的 `&'static str`。
            let next: &'static str = next;
            targets[target_count] = next;
            target_count += 1;
        }
        for (_, target) in branches {
            if !targets[..target_count].contains(target) {
                targets[target_count] = target;
                target_count += 1;
            }
        }
        for target in targets.iter().take(target_count) {
            if target.is_empty() {
                continue;
            }
            let Some(step) = content.event_step(target) else {
                continue;
            };
            let specs = step.entry_at(level, rd_run::state::A_EVENTS_WORSE);
            if specs.len() > rd_run::state::MAX_EVENT_EFFECTS {
                return fail(session, "进入效果超过上限");
            }
            for (index, spec) in specs.iter().enumerate() {
                let named = spec.effect.split_once(':').map(|(_, payload)| payload);
                let Some((effect, _payload)) = effect_from(spec.effect, i32::from(spec.amount))
                else {
                    return fail(session, "进入效果的词读不出来");
                };
                entry_pool[entry_count][index] = (effect, named);
            }
            entry_len[entry_count] = specs.len();
            entry_ids[entry_count] = target;
            entry_count += 1;
        }
    }
    let mut entry_pairs: [(&'static str, &[(rd_run::state::EventEffect, Option<&'static str>)]); rd_run::state::MAX_EVENT_BRANCHES] =
        [("", &[]); rd_run::state::MAX_EVENT_BRANCHES];
    for index in 0..entry_count {
        entry_pairs[index] = (entry_ids[index], &entry_pool[index][..entry_len[index]]);
    }
    let event_move = rd_run::state::EventMove {
        effects: &parsed[..specs.len()],
        next,
        branches,
        // §286：`Fight` 选项不走分支（它收尾整个事件）。
        entry: &entry_pairs[..entry_count],
        fight: choice.fight,
    };
    let outcome = session
        .state
        .resolve_event_effects(&event_move, &pool)
        .map(|_| 0i32);''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm: EventMove assembled')
    print('NEXT: rd_run_fight_begin 接受 event_fight + 新导出 rd_run_event_fight')


main()
