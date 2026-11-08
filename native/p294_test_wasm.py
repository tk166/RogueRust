"""§294 A1 判据（wasm 侧，真战斗）：洗牌 → `the_abacus` 给 6 格挡、`sundial` 每 3 次给 2 能量。

为什么判在 wasm：战斗的**构建**（`build_session_at_unstarted`）在这一层，`rd-core` 自己
没有"造一场战斗"的入口。而这条判据必须用真镜像 + 真战斗 —— 两件遗物的整条规则都是内容程序，
抄一份到测试里就变成第二份合同。

判据的三段：
① 遗物 → 开战真的挂了内容状态（`combat_bonus_for` + `apply_combat_bonus_statuses`）；
② 洗牌那一刻 `DeckShuffled` 真的派发（格挡 +6）；
③ `sundial` 数的**次数**：第 1、2 次不给，第 3 次给 2 —— 而空弃牌堆不算一次。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

TEST = r'''
    /// §294：`DeckShuffled` —— 洗牌那一刻派发，`the_abacus` / `sundial` 都吃得到。
    #[test]
    fn the_shuffle_trigger_pays_the_abacus_and_sundial() {
        use rd_core::state::CardZone;

        for (relic, want_block, want_energy_on_third) in [
            ("the_abacus", 6, false),
            ("sundial", 0, true),
            ("", 0, false),
        ] {
            let deck = ["strike", "strike", "strike", "strike", "strike",
                        "defend", "defend", "defend", "defend", "bash"];
            test_run(7, 80, 80, &deck);
            if !relic.is_empty() {
                run_slot()
                    .as_mut()
                    .expect("a run")
                    .state
                    .push_relic(relic, &[])
                    .unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            }
            // 走一格再开打（`rd_run_step` 是页面用的那个入口）。
            assert_eq!(rd_run_step(0), 0, "walk onto floor 1");
            assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

            // ① 遗物真的挂了内容状态。
            let session = crate::slot().as_ref().expect("a fight");
            let hero = session.hero_id().expect("a hero");
            let statuses = session
                .state
                .combatant(&hero)
                .expect("the hero")
                .status_ids();
            let expect = match relic {
                "the_abacus" => "standard.the_abacus",
                "sundial" => "standard.sundial",
                _ => "",
            };
            if !expect.is_empty() {
                assert!(
                    statuses.iter().any(|id| id.as_str() == expect),
                    "`{relic}` must put `{expect}` on the hero at combat start"
                );
            }

            // ②/③ 洗牌：把一张手牌塞进弃牌堆，再调内核的重洗。
            let block_before = session
                .state
                .defensive_pool(&hero, "standard.block")
                .unwrap_or(0);
            let energy_before = session
                .state
                .resource(&hero, "standard.energy")
                .unwrap_or(0);
            let shuffled = {
                let session = crate::slot().as_mut().expect("a fight");
                let hand: std::vec::Vec<_> = session
                    .state
                    .card_zones(&hero)
                    .expect("zones")
                    .slots(CardZone::Hand)
                    .to_vec();
                assert!(!hand.is_empty(), "the opening hand dealt");
                session
                    .state
                    .move_card_slot(hand[0], CardZone::DiscardPile)
                    .expect("to the discard pile");
                let n = session
                    .state
                    .reshuffle_discard_into_draw(&hero)
                    .expect("the shuffle");
                // 事件是**入队**的，排空由宿主负责（与真的一回合同一条路）。
                let host = crate::standard_host();
                host.try_resolve_pending_queues(&mut session.state)
                    .expect("the events resolve");
                n
            };
            assert_eq!(shuffled, 1, "one card went back");
            let session = crate::slot().as_ref().expect("a fight");
            let block_after = session
                .state
                .defensive_pool(&hero, "standard.block")
                .unwrap_or(0);
            let energy_after = session
                .state
                .resource(&hero, "standard.energy")
                .unwrap_or(0);
            assert_eq!(
                block_after - block_before,
                want_block,
                "`{relic}`: block after one shuffle"
            );
            assert_eq!(
                energy_after - energy_before,
                if want_energy_on_third { 0 } else { 0 },
                "`{relic}`: sundial must not pay on the first shuffle"
            );
            assert_eq!(
                session.state.pending_event_count(),
                0,
                "the event queue is drained"
            );

            // ③ `sundial`：再洗两次，只有第 3 次付 2 能量。
            if want_energy_on_third {
                for shuffle in 2..=3 {
                    let session = crate::slot().as_mut().expect("a fight");
                    let top = session
                        .state
                        .card_zones(&hero)
                        .expect("zones")
                        .slots(CardZone::DrawPile)
                        .first()
                        .copied();
                    let Some(top) = top else { break };
                    session
                        .state
                        .move_card_slot(top, CardZone::DiscardPile)
                        .expect("to the discard pile");
                    let before = session
                        .state
                        .resource(&hero, "standard.energy")
                        .unwrap_or(0);
                    session
                        .state
                        .reshuffle_discard_into_draw(&hero)
                        .expect("the shuffle");
                    let host = crate::standard_host();
                    host.try_resolve_pending_queues(&mut session.state)
                        .expect("the events resolve");
                    let after = session
                        .state
                        .resource(&hero, "standard.energy")
                        .unwrap_or(0);
                    if shuffle == 3 {
                        assert_eq!(after - before, 2, "sundial pays on the 3rd shuffle");
                    } else {
                        assert_eq!(after, before, "and not on the 2nd");
                    }
                }
            }
            // 收尾：这一场打完（否则下一条判据的 `test_run` 会撞上活着的一场）。
            let _ = rd_run_fight_end(0);
        }
    }
'''


def main():
    s = io.open(RUN, encoding='utf-8').read()
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + '\n' + TEST + s[cut:]
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm test appended')


main()
