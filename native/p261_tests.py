"""§261 判据：五件"战斗开始类"遗物。

这批**必须跑真回合**，不能像 §260 那样手工驱动触发器 —— 因为三件的规则就住在回合机的
固定顺序里（补能量 #2 → 触发器 #4/#5 → 抽牌 #6 → 清格挡 #7）：

* `lantern` 的 +1 必须在**补能量之后**（否则会被 3 点覆盖）；
* `bag_of_preparation` 的 +2 必须在**抽 5 之前**（否则手牌上限会裁掉它）；
* `ice_cream` 是"补能量"这一步的**分支**；
* `calipers` 是"清格挡"这一步的**分支**。

手工调 `try_run_turn_started_triggers` 会把前三件测成"好像对"，却完全测不到顺序。
所以这里用 `Session::step_end_turn()` 走完整轮，读**能量数 / 手牌数 / 格挡数**。

## 两半

* rd-run 的 `the_five_combat_start_relics_wire_their_own_carrier`：接线（含 `calipers` 的
  **15 层**与 `du_vu_doll` 的 `per_curse` 表 —— 抄错数字/抄错表只有逐条比才看得出）。
* 这里：行为。每条都两面（该给的给了 / 不该给的没给）。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §260：回合末/回合初那八条状态**真的按回合生效**。'''

WASM_TESTS = r'''    /// §261：五件"战斗开始类"遗物 —— **跑真回合**。
    ///
    /// 用 `step_end_turn()`（完整一轮）而不是手工调触发器：`lantern` / `bag_of_preparation`
    /// 的正确性依附于 turn-start 七步的**顺序**；`ice_cream` / `calipers` 是那七步里的两个分支。
    /// 只调触发器的话，`lantern` 会"看起来生效"（能量确实 +1），却测不到它是否在补能量之后。
    #[test]
    fn the_combat_start_relics_change_the_right_step_of_the_turn() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一个辅助：建一场对 Cultist 的战斗，并给英雄挂上某条载体状态（layer = 层数）。
        let setup = |status_id: &str, stacks: i32, seed: i32| {
            let session = build_session_at(seed, "enc_cultist", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("{status_id}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|pool| pool.key.as_str() == "standard.energy")
                        .map_or(-1, |pool| pool.pool.current)
                })
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.defensive_pools()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.block")
                    .map_or(0, |pool| pool.pool.current)
            })
        };
        let end_turn = || {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        };
        let give_block = |amount: i32| {
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

        // ---- 基准：不带遗物时第 1 回合 3 能量 / 5 张手牌。基准错了后面全是误报。
        {
            build_session_at(41, "enc_cultist", 200, None, 0, 0).expect("baseline");
            install_session(build_session_at(41, "enc_cultist", 200, None, 0, 0).expect("b"));
            assert_eq!(energy(), 3, "baseline: 3 energy on turn 1");
            assert_eq!(hand(), 5, "baseline: 5 cards on turn 1");
            take_session();
        }

        // ---- Lantern：第 1 回合 4 点（3 + 1），第 2 回合回到 3 点。
        setup("standard.lantern", 1, 42);
        assert_eq!(energy(), 4, "Lantern: 3 + 1 on the first turn");
        end_turn();
        // ⚠️ 第 2 回合是 3 —— 而且这一条才是真正的判据：如果 +1 发生在补能量**之前**，
        // 第 1 回合照样是 4，只有"第 2 回合回到 3"和"能量不是 3+1+…"能区分。
        assert_eq!(energy(), 3, "Lantern: back to 3 from turn 2 on");
        take_session();

        // ---- Bag of Preparation：第 1 回合 7 张（5 + 2），第 2 回合回到 5 张。
        setup("standard.bag_of_preparation", 1, 43);
        assert_eq!(hand(), 7, "Bag of Preparation: 5 + 2 on the first turn");
        end_turn();
        assert_eq!(hand(), 5, "Bag of Preparation: back to 5 from turn 2 on");
        take_session();

        // ---- Ice Cream：没用掉的能量跨回合累积。
        setup("standard.ice_cream", 1, 44);
        assert_eq!(energy(), 3, "Ice Cream: still 3 at the start");
        // 花掉 1 点：剩 2。下一回合应当是 2 + 3 = 5（而不是 3）。
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::LoseResource {
                    target: Some(cid_in("hero")),
                    resource: rd_core::state::ResourceId::new("standard.energy")
                        .expect("energy"),
                    amount: 1,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("spend 1");
        }
        assert_eq!(energy(), 2, "Ice Cream: 2 left after spending 1");
        end_turn();
        assert_eq!(energy(), 5, "Ice Cream: 2 carried + 3 refilled");
        take_session();

        // ---- Calipers：回合开始只失去 15 点，而不是全部。
        setup("standard.calipers", 15, 45);
        give_block(40);
        assert_eq!(block(), 40, "Calipers: 40 Block in place");
        end_turn();
        // 回合开始那一刻是 40 —— 防御方（Cultist）的回合里英雄不掉格挡，所以下一回合开始
        // 还是 40 ⇒ 失去 15 ⇒ 25。
        assert_eq!(block(), 25, "Calipers: 40 - 15 = 25, not 0");
        take_session();

        // 少于 15 点 ⇒ 全没（`max(0, live - 15)`）。
        setup("standard.calipers", 15, 46);
        give_block(6);
        end_turn();
        assert_eq!(block(), 0, "Calipers: 6 - 15 clamps to 0");
        take_session();

        // 不带 Calipers ⇒ 全清（默认路径没被这次改动破坏）。
        install_session(build_session_at(47, "enc_cultist", 200, None, 0, 0).expect("plain"));
        give_block(40);
        end_turn();
        assert_eq!(block(), 0, "without Calipers the block is cleared as before");
        take_session();
    }

'''

RUN_TESTS = r'''    /// §261：五件"战斗开始类"遗物的**接线**。
    ///
    /// 逐条比，而且 `calipers` 比的是**15 层**、`du_vu_doll` 比的是它落在 **per_curse 那张表**
    /// 上（不是 `statuses`）。抄错数字、抄错表，只有逐条比才看得出来（§186/§260 都踩过）。
    #[test]
    fn the_five_combat_start_relics_wire_their_own_carrier() {
        // (遗物, 状态 id, 层数)
        let carrier = [
            ("lantern", "standard.lantern", 1),
            ("bag_of_preparation", "standard.bag_of_preparation", 1),
            ("ice_cream", "standard.ice_cream", 1),
            ("calipers", "standard.calipers", 15),
        ];
        for (relic, status_id, stacks) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, stacks, "{relic}: the stacks are the wiki's number");
            assert_eq!(bonus.per_curse_status_count, 0, "{relic}: not a per-curse relic");
        }

        // `du_vu_doll` 落在**另一张表**上：层数是"每张诅咒多少"，不是总数。
        let mut run = ironclad();
        run.push_relic("du_vu_doll").expect("du_vu_doll");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "du_vu_doll has no fixed-stack status");
        assert_eq!(bonus.per_curse_status_count, 1, "du_vu_doll uses the per-curse table");
        let entry = bonus.per_curse_statuses[0].expect("an entry");
        assert_eq!(entry.id, "standard.strength", "du_vu_doll grants Strength");
        assert_eq!(entry.stacks, 1, "1 Strength per Curse");
        assert!(!bonus.is_empty(), "a per-curse relic is not an empty bonus");
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_combat_start_relics_change_the_right_step' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §260：八件遗物的**接线**'''
    assert src.count(anchor) == 1
    assert 'the_five_combat_start_relics_wire_their_own_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(
        src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
