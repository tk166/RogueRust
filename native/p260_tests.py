"""§260 判据：八件"战斗开始类 / 回合末类"遗物。

两半分开测，因为它们是两条不同的链：

* **接线**（`rd-run`）：`push_relic` 之后 `combat_bonus()` 里必须出现那条状态、且只有它。
  这一半能抓到"遗物写进了表里但没接线"（最典型的漏法：`relic_effect` 忘了那一行）。
* **规则**（`rd-wasm`）：把状态挂到英雄身上，驱动 `try_run_turn_started_triggers` /
  `try_run_turn_ended_triggers`，看**回合语义**对不对（第 2 回合才是 14 格挡、第 7 回合才 52 伤害…）。
  这一半能抓到"接了线但规则写错"，而只有前一半的话，一件"每回合都给 14 格挡"的错也会绿。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

RUN_ANCHOR = '''    // ---- settling a node ---------------------------------------------------------------------'''
WASM_ANCHOR = '''    /// §209：Curl Up —— **首次**掉血时按掷骰加格挡，之后自我摘除；被完全格挡的一击**不**消耗它。'''

RUN_TESTS = r'''    /// §260：八件遗物的**接线** —— 每件都必须把**它自己那条**状态挂到英雄身上。
    ///
    /// 一条表一个断言（不是"至少有一个"）：`StartCombatStatus` 的参数写错（抄了邻居的状态 id）
    /// 只有逐条比才看得出来，而抄邻居在这个仓库里已经发生过不止一次（§186）。
    #[test]
    fn the_eight_turn_shaped_relics_wire_their_own_status() {
        let expectations = [
            ("orichalcum", "standard.orichalcum"),
            ("mercury_hourglass", "standard.mercury_hourglass"),
            ("horn_cleat", "standard.horn_cleat"),
            ("captains_wheel", "standard.captains_wheel"),
            ("stone_calendar", "standard.stone_calendar"),
            ("cloak_clasp", "standard.cloak_clasp"),
            ("incense_burner", "standard.incense_burner"),
            ("pocketwatch", "standard.pocketwatch"),
        ];
        for (relic, status_id) in expectations {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: exactly one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: wires its own status");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
            assert_eq!(bonus.block, 0, "{relic}: no start-of-combat Block");
        }
    }

'''

WASM_TESTS = r'''    /// §260：回合末/回合初那八条状态**真的按回合生效**。
    ///
    /// 每条都两面测（"该给的时候给了"＋"不该给的时候没给"），因为"每回合都给"这种错法
    /// 只测正面是看不出来的。
    #[test]
    fn the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一个辅助：建一场对 Cultist 的战斗，并把某条状态挂到英雄身上。
        let setup = |status_id: &str, seed: i32| {
            let session = build_session_at(seed, "enc_cultist", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("{status_id}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier status");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let hero_block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| c.defensive_pool())
        };
        let hero_hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("cultist")).map_or(-1, |c| c.health_current)
        };
        let hero_status = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(0, |c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
        };
        let start_turn = || {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_started_triggers(&mut session.state, &cid_in("hero"))
                .expect("turn started");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let end_turn = || {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_ended_triggers(&mut session.state, &cid_in("hero"))
                .expect("turn ended");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let set_block = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainBlock {
                    target: Some(cid_in("hero")),
                    amount,
                    from_card: false,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("block");
        };

        // ---- Orichalcum：回合末**没有格挡**才给 6。两面。
        setup("standard.orichalcum", 31);
        set_block(5);
        end_turn();
        assert_eq!(hero_block(), 5, "Orichalcum leaves you alone when you already have Block");
        {
            // 把格挡清掉（直接写回 0，模拟"这回合没攒格挡"）。
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let combatant = session.state.combatant_mut(&hero).expect("hero");
            combatant.set_defensive_pool(0, 0, None).expect("clear block");
        }
        end_turn();
        assert_eq!(hero_block(), 6, "no Block at end of turn ⇒ +6");
        take_session();

        // ---- Mercury Hourglass：每次回合初对所有敌人 3 点。
        setup("standard.mercury_hourglass", 32);
        let before = enemy_hp();
        start_turn();
        assert_eq!(enemy_hp(), before - 3, "3 damage to ALL enemies at the start of your turn");
        take_session();

        // ---- Horn Cleat：**第 2 回合**才给 14（第 1 回合不给）。
        setup("standard.horn_cleat", 33);
        start_turn();
        assert_eq!(hero_block(), 0, "turn 1: nothing yet");
        start_turn();
        assert_eq!(hero_block(), 14, "turn 2: +14 Block");
        start_turn();
        assert_eq!(hero_block(), 14, "turn 3: nothing more");
        take_session();

        // ---- Captain's Wheel：**第 3 回合**才给 18。
        setup("standard.captains_wheel", 34);
        start_turn();
        start_turn();
        assert_eq!(hero_block(), 0, "turns 1-2: nothing yet");
        start_turn();
        assert_eq!(hero_block(), 18, "turn 3: +18 Block");
        take_session();

        // ---- Stone Calendar：第 7 回合末才 52 伤害。
        setup("standard.stone_calendar", 35);
        let before = enemy_hp();
        for turn in 1..=6 {
            end_turn();
            assert_eq!(enemy_hp(), before, "turn {turn}: not yet");
        }
        end_turn();
        assert_eq!(enemy_hp(), before - 52, "turn 7: 52 damage to ALL enemies");
        take_session();

        // ---- Cloak Clasp：回合末按**手牌张数**给格挡。
        setup("standard.cloak_clasp", 36);
        let hand = hero_hand();
        assert!(hand > 0, "the hero starts with a hand");
        end_turn();
        assert_eq!(hero_block(), hand as i32, "1 Block per card in hand");
        take_session();

        // ---- Incense Burner：每 6 回合 1 层无形。
        setup("standard.incense_burner", 37);
        for turn in 1..=5 {
            start_turn();
            assert_eq!(hero_status("standard.intangible"), 0, "turn {turn}: not yet");
        }
        start_turn();
        assert_eq!(hero_status("standard.intangible"), 1, "turn 6: 1 Intangible");
        take_session();

        // ---- Pocketwatch：上回合 ≤3 张 ⇒ 这回合初抽 3。
        setup("standard.pocketwatch", 38);
        {
            // 上回合打了 4 张：**不该**抽。
            let session = slot().as_mut().expect("session");
            session.state.cards_played_last_turn = 4;
        }
        let before = hero_hand();
        start_turn();
        assert_eq!(hero_hand(), before, "4 cards last turn ⇒ no extra draw");
        {
            let session = slot().as_mut().expect("session");
            session.state.cards_played_last_turn = 3;
        }
        let before = hero_hand();
        start_turn();
        assert_eq!(hero_hand(), before + 3, "3 or fewer ⇒ draw 3");
        take_session();
    }

'''


def main():
    src = io.open(RUN, encoding='utf-8').read()
    assert src.count(RUN_ANCHOR) == 1
    assert 'the_eight_turn_shaped_relics_wire_their_own_status' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(
        src.replace(RUN_ANCHOR, RUN_TESTS + RUN_ANCHOR))

    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_turn_shaped_relic_statuses_fire_on_the_turn' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))
    print('tests appended: rd-run 1, rd-wasm 1')


main()
