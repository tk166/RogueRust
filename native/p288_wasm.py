"""§288 wasm：`After` 的"回到事件"、事件池按楼层筛、新词的效果码。"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:90])
    return s.replace(old, new)


def main():
    s = io.open(RUN, encoding='utf-8').read()

    # ── ① 回到事件：回血之后、掷奖励**之前**先问
    s = patch(s, '''        // `Burning Blood` and friends (`inv:§2`), now with a call site.
        if let Err(e) = session.state.end_of_combat() {
            let message = describe(&e);
            return fail(session, &message);
        }''',
'''        // `Burning Blood` and friends (`inv:§2`), now with a call site.
        if let Err(e) = session.state.end_of_combat() {
            let message = describe(&e);
            return fail(session, &message);
        }
        // §288：**这一场打完要回到事件**？（`The Colosseum` 的第一场）
        //
        // 在掷奖励**之前**问，问到就返回：wiki 说那场战斗 "gives no rewards" —— 它的奖励是
        // "事件继续"。节点的账也还没花完（事件还要走到 `[COWARDICE]`/`[VICTORY]`），
        // 所以这里**不能** `mark_resolved`。
        if session.state.resume_event_after_fight() {
            return 1;
        }''')

    # ── ② 事件池按楼层筛
    s = patch(s, '''        let Some(pool) = image.event_pool(pool_name) else {''',
'''        // §288：**先按楼层筛**再掷（`Dead Adventurer` 只在第 7 层之后出现）。
        // 先筛后掷而不是"掷了不合格再重掷"：后者会让随机数被看不见的规则吃掉。
        let floor = session.state.floor();
        let Some(pool) = image.event_pool_at(pool_name, floor) else {''')

    # ── ③ 新词的效果码
    s = patch(s, '''        | EventEffect::FightGoldBonus(_)
        | EventEffect::FightNoRelic => -1,''',
'''        | EventEffect::FightGoldBonus(_)
        | EventEffect::FightNoRelic
        // §288：同理 —— 落点在战斗结算里（`The Colosseum` 的定数奖励）。
        | EventEffect::FightGoldSet(_)
        | EventEffect::FightRelicRarity(_)
        | EventEffect::FightExtraRelic(_) => -1,''')

    s = patch(s, '''        // §287：欠账金币的"数量"就是它本身（页面写"下一场战斗多得 N 金币"）。
        EventEffect::FightGoldBonus(n) => n,''',
'''        // §287：欠账金币的"数量"就是它本身（页面写"下一场战斗多得 N 金币"）。
        EventEffect::FightGoldBonus(n) => n,
        // §288：定数金币同理。
        EventEffect::FightGoldSet(n) => n,''')

    s = patch(s, '''        | EventEffect::FightNoRelic
        | EventEffect::GainCurse''',
'''        | EventEffect::FightNoRelic
        | EventEffect::FightRelicRarity(_)
        | EventEffect::FightExtraRelic(_)
        | EventEffect::GainCurse''')

    # ── ④ `EventMove` 带 `After`
    s = patch(s, '''        // §287：`Encounter`（池名）。空 = 按档位用本幕的标准池。
        fight_pool: choice.fight_pool,
    };''','''        // §287：`Encounter`（池名）。空 = 按档位用本幕的标准池。
        fight_pool: choice.fight_pool,
        // §288：`After`（打完回到事件哪一段）。空 = 战斗结算整个房间。
        fight_after: choice.fight_after,
    };''')

    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm: resume / floor filter / codes')


main()
