"""§283 判据：① "Bite 不连三次"（记**最近两次**招式）；② `snecko_eye` 遗物。

两条都放在 `rd-wasm`（真内容 + 真 ABI），因为要证的是**可观察**行为：

① 的判据形状很关键 —— **不能**只验"两次 Bite 之后出 Tail Whip"（那只说明规则存在）；
   还要验**反面**：只有一次 Bite 之后**仍然可能**出 Bite（否则"永远不出 Bite"也全绿，
   而那会让 Snecko 变成一只只会 Tail Whip 的怪）。

② 两侧：带 Eye 抽 7 张（5 + 2）且首回合就被挂上 Confused；不带则抽 5 张、没有 Confused。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

ANCHOR = '''    /// §282：`Confusion`（wiki: *Confused*）—— 抽到的牌价格重掷成 0..3。'''

TESTS = r'''    /// §283：Snecko 的 "will not use Bite three times in a row"。
    ///
    /// 内核的 `intent.selfHasCounter` 只读**一个**计数器，所以内容在每个动作里写了
    /// `prev_move = last_move; last_move = 本招`。这条判据钉的是**规则真的读到了 prev**：
    /// * 反面：`last_move = Bite`、`prev_move = 别的` ⇒ 仍然允许 Bite（否则那只怪只会 Tail Whip）；
    /// * 正面：两次都是 Bite ⇒ 强制 Tail Whip。
    ///
    /// 走真内容：`snecko` 的动作与规则都在镜像里，这里只**摆好计数器**再问"下一招是什么"。
    #[test]
    fn snecko_never_bites_three_times_in_a_row() {
        use rd_core::state::{CombatantId, CounterId};
        // Bite 的索引写进 `last_move`：内容里 `snecko.bite` 写的是 2。
        const BITE: i32 = 2;
        const TAIL_WHIP: i32 = 3;

        let next_move = |prev: i32, last: i32, round: i32| -> String {
            let session = crate::slot_for_encounter("enc_snecko");
            let image = content();
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .expect("the snecko")
                .id
                .clone();
            {
                let key = |name: &str| CounterId::new(name).expect("a counter id");
                let combatant = session.state.combatant_mut(&enemy).expect("the snecko");
                combatant
                    .set_counter(key("prev_move"), prev)
                    .expect("prev_move fits");
                combatant
                    .set_counter(key("last_move"), last)
                    .expect("last_move fits");
            }
            session.state.current_round = round;
            let at = rd_core::intent::locate_enemy(image, session.encounter, &enemy)
                .expect("locate")
                .expect("the snecko has a record");
            let choice = rd_core::intent::select_action(
                &session.state,
                image,
                at,
                &enemy,
                round,
            )
            .expect("select_action")
            .expect("the snecko must pick something");
            choice.action_id.to_string()
        };

        // 反面：只有**上一次**是 Bite ⇒ 仍可能出 Bite。挑一个真的出 Bite 的轮次来证
        // （规则是加权 60/40，所以扫几个轮次，至少一个必须是 Bite；一个都没有就说明
        // "永远不出 Bite"，那同样是错的）。
        let mut saw_bite = false;
        for round in 2..12 {
            if next_move(TAIL_WHIP, BITE, round).ends_with(".bite") {
                saw_bite = true;
                break;
            }
        }
        assert!(
            saw_bite,
            "after a single Bite the snecko never picked Bite again -- the rule is always on"
        );

        // 正面：最近**两次**都是 Bite ⇒ 只能是 Tail Whip（扫 10 个轮次，一次 Bite 都不许有）。
        for round in 2..12 {
            let picked = next_move(BITE, BITE, round);
            assert!(
                picked.ends_with(".tail_whip"),
                "round {round}: two Bites in a row must force Tail Whip, got {picked}"
            );
        }
    }

    /// §283：`snecko_eye`（Boss 遗物）—— 每回合多抽 2 张，且**开局就被挂 Confused**。
    ///
    /// 两侧：带 Eye 时手牌 7 张（5 + 2）且状态里有 `standard.confusion`；不带时 5 张、没有。
    #[test]
    fn snecko_eye_draws_two_more_and_confuses_at_the_start() {
        let fight = |with_eye: bool, seed: i32| -> (usize, bool) {
            test_run(seed, 80, 80, &["strike"; 12]);
            assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
            assert_eq!(rd_run_begin_node(), 0);
            if with_eye {
                let pool = reward_pool(content()).expect("the card pool");
                run_slot()
                    .as_mut()
                    .expect("run")
                    .state
                    .push_relic("snecko_eye", &pool)
                    .expect("snecko_eye is implemented");
            }
            assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
            let session = crate::slot().as_ref().expect("env session");
            let confused = session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "player")
                .any(|c| {
                    c.statuses()
                        .iter()
                        .any(|s| s.definition_id.as_str() == "standard.confusion")
                });
            (session.hand_costs.len(), confused)
        };

        let (plain_hand, plain_confused) = fight(false, 7);
        assert_eq!(plain_hand, 5, "without Snecko Eye the opening hand is five");
        assert!(!plain_confused, "and nothing is Confused");

        let (eye_hand, eye_confused) = fight(true, 7);
        assert_eq!(
            eye_hand, 7,
            "Snecko Eye draws 2 additional cards (5 + 2 = 7), got {eye_hand}"
        );
        assert!(
            eye_confused,
            "Snecko Eye starts each combat with Confused"
        );
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'snecko_never_bites_three_times_in_a_row' not in s
    s = s.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§283 wasm tests appended')


main()
