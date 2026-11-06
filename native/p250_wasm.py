"""§250 内核（4/4）：`rd-wasm` 的两处桥。

1. **战斗里赚到的金币**：`CombatState.gold_gained` 在 `fight_end` 被加进运行层的金币。
   与 §201 的 `carried_gold`（偷走的钱，要**减**）对称 —— 但必须走**两个**参数而不是
   合成一个 `gold_delta`：`apply_fight_outcome` 的两个分支（胜/逃）对它们的处理不同，
   而回放记录里也要能分开读（`session.log` 的文本格）。

   ⚠️ 回放一致性：`carried_gold` 进的是 `session.log(...)` 的**文本格**，`gold_gained` 走同一条路
   —— 一次战斗的结算在回放时必须能重算出同样的金币，否则"同一份录像两次数值不同"。

2. **两个新 `ChoiceThen` 的 ABI 编号**：`to hand and free` = 7、`bottom of the draw pile and
   free` = 8。与既有编号同一条纪律：**不跟 Rust 枚举的 `as i32` 走**，因为页面按这个数
   写句子（"拿进手牌（它这次免费）" vs "放到抽牌堆底（它这次免费）"）。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

RUN_PATCHES = [
    # 读 gold_gained（与 carried_gold 并排）
    ('''    let carried_gold = crate::combat_gold_carried_away();
    // Captured before the run is borrowed mutably below.''',
     '''    let carried_gold = crate::combat_gold_carried_away();
    // §250：这一场战斗里**赚到**的金币（`Hand of Greed` 的 "If Fatal, gain 20 Gold"）。
    // 与 `carried_gold` 一起在 `take_session()` **之前**读 —— 之后战斗就没了。
    let gained_gold = crate::combat_gold_gained();
    // Captured before the run is borrowed mutably below.'''),
    ('''    session.log(
        K_FIGHT_END,
        hero_hp,
        (i32::from(boss_fight) << 1 | i32::from(elite_fight)) | (result << 4),
        &std::format!("{carried_gold}"),
    );
    let verdict =
        apply_fight_outcome(session, hero_hp, result, elite_fight, boss_fight, carried_gold);''',
     '''    session.log(
        K_FIGHT_END,
        hero_hp,
        (i32::from(boss_fight) << 1 | i32::from(elite_fight)) | (result << 4),
        // §250：两个数都在这一格里（`carried,gained`）—— 回放要能重算出同样的结算。
        &std::format!("{carried_gold},{gained_gold}"),
    );
    let verdict = apply_fight_outcome(
        session,
        hero_hp,
        result,
        elite_fight,
        boss_fight,
        carried_gold,
        gained_gold,
    );'''),
    # 函数签名 + 加金币
    ('''fn apply_fight_outcome(
    session: &mut RunSession,
    hero_hp: i32,
    result: i32,
    elite_fight: bool,
    boss_fight: bool,
    carried_gold: i32,
) -> i32 {''',
     '''fn apply_fight_outcome(
    session: &mut RunSession,
    hero_hp: i32,
    result: i32,
    elite_fight: bool,
    boss_fight: bool,
    carried_gold: i32,
    gained_gold: i32,
) -> i32 {'''),
    ('''    if carried_gold > 0 {
        session.state.adjust_gold(-carried_gold);
    }''',
     '''    if carried_gold > 0 {
        session.state.adjust_gold(-carried_gold);
    }
    // §250：战斗里赚到的金币（`Hand of Greed`）。**在偷走的钱之后**结算，两个数各走各的路：
    // 偷走的是"从现有金币里扣"（`adjust_gold` 自己钳到 0），赚到的是"往现有金币里加"。
    // 顺序在这里不可观察（加法可交换），写下来是因为"哪个先"以后若变成乘数就会可观察。
    if gained_gold > 0 {
        session.state.adjust_gold(gained_gold);
    }'''),
]

LIB_PATCHES = [
    ('''pub(crate) fn combat_gold_carried_away() -> i32 {''',
     '''/// §250：这一场战斗里**赚到**的金币（`node.gainGold` 累加）。
///
/// 与 [`combat_gold_carried_away`] 成对：那本是"被偷走、要减"，这本是"赚到手、要加"。
pub(crate) fn combat_gold_gained() -> i32 {'''),
    ('''            ChoiceThen::ToDrawPileTop => 6,''',
     '''            ChoiceThen::ToDrawPileTop => 6,
            // §250: `Discovery` -- "add it to your hand, it costs 0". A **new number**: the page
            // writes "免费" into the sentence from it, and reusing `ToHand` would silently promise
            // a price the kernel is not charging.
            ChoiceThen::ToHandFree => 7,
            // §250: `Forethought` -- "on the **bottom** of your draw pile, costs 0".
            ChoiceThen::ToDrawPileBottomFree => 8,'''),
]


# `flee_fight`（Smoke Bomb）与 `replay_fight`（回放）也必须传这两个数。
RUN_EXTRA = [
    ("""    let carried_gold = crate::combat_gold_carried_away();
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let elite_fight = session.elite_fight;
    let boss_fight = session.boss_fight;""",
     """    let carried_gold = crate::combat_gold_carried_away();
    // §250：逃走的战斗也要把"战斗里赚到的金币"带上 —— `Hand of Greed` 的钱不是奖励
    // （Smoke Bomb 的 "no rewards" 说的是奖励），它已经在战斗里到手了。
    let gained_gold = crate::combat_gold_gained();
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let elite_fight = session.elite_fight;
    let boss_fight = session.boss_fight;"""),
    ("""    session.log(K_FIGHT_END, hero_hp, 3 << 4, &std::format!("{carried_gold}"));
    let verdict = apply_fight_outcome(session, hero_hp, 3, false, false, carried_gold);""",
     """    session.log(
        K_FIGHT_END,
        hero_hp,
        3 << 4,
        &std::format!("{carried_gold},{gained_gold}"),
    );
    let verdict =
        apply_fight_outcome(session, hero_hp, 3, false, false, carried_gold, gained_gold);"""),
    # 回放的调用点：把文本格解析成两个数
    ("""                let carried = payload.parse::<i32>().unwrap_or(0);
                let _ = replay_fight(session, a, b, carried);""",
     """                let gold = parse_fight_gold(payload);
                let _ = replay_fight(session, a, b, gold);"""),
    # 测试里的调用点
    ("""            let verdict = replay_fight(session, health - 5, 1 << 4, 0);""",
     """            let verdict = replay_fight(session, health - 5, 1 << 4, (0, 0));"""),
    ("""            let verdict = apply_fight_outcome(
                run_slot().as_mut().expect("run"), 70, 1, false, false, carried);""",
     """            let verdict = apply_fight_outcome(
                run_slot().as_mut().expect("run"), 70, 1, false, false, carried, 0);"""),
    # 回放：从记录里读**两个**数（老录像只有一个数 ⇒ 第二个当 0，这是唯一向后兼容的读法）
    ("""fn replay_fight(session: &mut RunSession, hero_hp: i32, flags: i32, carried_gold: i32) -> i32 {
    let elite = flags & 1 != 0;
    let boss = flags & 2 != 0;
    let result = flags >> 4;
    apply_fight_outcome(session, hero_hp, result, elite, boss, carried_gold)
}""",
     """fn replay_fight(session: &mut RunSession, hero_hp: i32, flags: i32, gold: (i32, i32)) -> i32 {
    let elite = flags & 1 != 0;
    let boss = flags & 2 != 0;
    let result = flags >> 4;
    let (carried_gold, gained_gold) = gold;
    apply_fight_outcome(session, hero_hp, result, elite, boss, carried_gold, gained_gold)
}

/// §250：`K_FIGHT_END` 那一格文本里的两个数 —— `carried,gained`。
///
/// 老录像只有一个数（`carried`）。**第二个当 0** 是唯一向后兼容的读法：那时根本没有
/// `gainGold` 这条节点，所以"没赚到"是事实而不是猜测。
fn parse_fight_gold(text: &str) -> (i32, i32) {
    match text.split_once(',') {
        Some((carried, gained)) => (
            carried.parse().unwrap_or(0),
            gained.parse().unwrap_or(0),
        ),
        None => (text.parse().unwrap_or(0), 0),
    }
}"""),
]


def main():
    src = io.open(RUN, encoding='utf-8').read()
    if 'gained_gold' in src:
        RUN_DONE = True
    else:
        RUN_DONE = False
    if not RUN_DONE:
        for old, new in list(RUN_PATCHES) + list(RUN_EXTRA):
            assert src.count(old) == 1, ('run', old[:60], src.count(old))
            src = src.replace(old, new)
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src)
    print('run.rs patched (%d edits)' % len(RUN_PATCHES))

    src = io.open(LIB, encoding='utf-8').read()
    for old, new in LIB_PATCHES:
        assert src.count(old) == 1, ('lib', old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(LIB, 'w', encoding='utf-8', newline='\n').write(src)
    print('lib.rs patched (%d edits)' % len(LIB_PATCHES))


main()
