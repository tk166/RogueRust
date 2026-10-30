"""§155: tests for the elite-relic reward.

Two layers, because they fail differently:

* `rd-run` owns the rule ("elite and boss pay a relic, a normal fight does not, and a second copy of
  a held relic is never offered");
* `rd-wasm` owns the wiring (the ABI exposes it and `take_relic` goes through `push_relic`).

The rd-wasm test forces the payout instead of fighting an elite: winning a real elite needs a policy,
and the *reward* is not what a policy would be testing.
"""

import io

RUN = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"
WASM = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

RUN_TEST = '''
    /// §155：**精英和 Boss 给遗物，普通怪不给**，而且绝不会再给一件已经有的。
    ///
    /// StS 的精英奖励是"金币 + 三选一 + 一件遗物"，本内核之前只给前两样 —— 一条能走完的路，
    /// 但少了一整类反馈。这条测试盯的是**规则**（哪一档给、给的时候会不会重复）。
    #[test]
    fn an_elite_pays_a_relic_and_a_normal_fight_does_not() {
        let pool = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
            },
        ];
        let relics = ["burning_blood", "anchor", "vajra"];

        // A normal fight: no relic row at all.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        run.roll_reward(&pool, &[], &relics, FightKind::Normal)
            .expect("a normal reward");
        assert_eq!(run.reward_relic(), None, "a normal fight pays no relic");
        assert_eq!(
            run.take_relic(),
            Err(RunError::NoSuchRelic),
            "and taking one says so instead of doing nothing"
        );

        // An elite: a relic, and taking it lands in the relic list.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        let before = run.relics().len();
        run.roll_reward(&pool, &[], &relics, FightKind::Elite)
            .expect("an elite reward");
        let offered = run.reward_relic().expect("an elite pays a relic").to_string();
        assert!(
            relics.contains(&offered.as_str()),
            "{offered} is not in the pool"
        );
        run.take_relic().expect("take it");
        assert_eq!(run.relics().len(), before + 1, "the relic list grew");
        assert_eq!(
            run.relics().last().map(|id| id.as_str()),
            Some(offered.as_str()),
            "and it is the one that was offered"
        );
        assert_eq!(run.reward_relic(), None, "the row is empty after taking it");
        assert_eq!(run.take_relic(), Err(RunError::NoSuchRelic), "taking twice fails");

        // A held relic is never offered again: hold all three and the elite pays nothing.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        for relic in relics {
            run.push_relic(relic).expect("grant");
        }
        run.roll_reward(&pool, &[], &relics, FightKind::Elite)
            .expect("an elite reward with every relic held");
        assert_eq!(
            run.reward_relic(),
            None,
            "a full set means no relic, not a duplicate"
        );

        // A boss pays one too.
        let mut run = RunState::new(9, 80, 0, &DECK).expect("a run");
        run.roll_reward(&pool, &[], &relics, FightKind::Boss)
            .expect("a boss reward");
        assert!(run.reward_relic().is_some(), "a boss pays a relic");
    }
'''

with io.open(RUN, encoding="utf-8") as handle:
    source = handle.read()
if "fn an_elite_pays_a_relic_and_a_normal_fight_does_not" in source:
    print("rd-run test already present")
else:
    anchor = "    /// The pity offset ticks **once per card rolled**"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("rd-run anchor missing")
    source = source[:at] + RUN_TEST.strip("\n") + "\n\n" + source[at:]
    with io.open(RUN, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("rd-run test inserted")

WASM_TEST = '''
    /// §155：**精英奖励里的遗物能通过 ABI 拿到**（走 `push_relic` 这个唯一授予点）。
    ///
    /// 这里直接逼出一张奖励表（`roll_reward(FightKind::Elite)`），而不是打赢一场精英：
    /// 打赢需要一套出牌策略，而策略不是"奖励能不能拿"这件事的判据。
    #[test]
    fn the_elite_relic_reward_round_trips_through_the_abi() {
        reset(7);
        let relics = relic_pool(content());
        let pool = match full_pool(content()) {
            Ok(pool) => pool,
            Err(message) => panic!("{message}"),
        };
        let held_before = rd_run_observe(6);
        let offered = {
            let session = run_slot().as_mut().expect("session");
            session
                .state
                .roll_reward(&pool, &[], &relics, rd_run::state::FightKind::Elite)
                .expect("an elite reward")
        };
        let _ = offered;
        let len = rd_run_reward_relic_len();
        assert!(len > 0, "the reward table offers a relic");
        let mut buffer = std::vec![0u8; len as usize];
        unsafe { rd_run_reward_relic_into(buffer.as_mut_ptr()) };
        let id = String::from_utf8(buffer).expect("ascii");
        assert!(relics.contains(&id.as_str()), "{id} is not in the pool");

        assert_eq!(rd_run_take_relic(), 0, "take it: {}", run_error_text());
        assert_eq!(
            rd_run_observe(6),
            held_before + 1,
            "the relic count moved"
        );
        assert_eq!(rd_run_reward_relic_len(), 0, "the row is empty after taking it");
        assert_eq!(rd_run_take_relic(), -1, "taking it twice is refused, not ignored");
    }
'''

with io.open(WASM, encoding="utf-8") as handle:
    source = handle.read()
if "fn the_elite_relic_reward_round_trips_through_the_abi" in source:
    print("rd-wasm test already present")
else:
    anchor = "    /// §152：五种新的药水形状**真的有效**"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("rd-wasm anchor missing")
    source = source[:at] + WASM_TEST.strip("\n") + "\n\n" + source[at:]
    with io.open(WASM, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("rd-wasm test inserted")
