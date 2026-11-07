"""§262 判据：七件"每第 N 张某类型牌"的遗物。

这批的规则全在**触发器**里，所以判据必须**真的打牌**（并排空队列），不能只看状态挂上了没有：

* `CardPlayed` 触发器在卡牌节目**之后**派发 ⇒ 只有真打一张牌、再 `try_resolve_pending_queues`，
  计数才会动；
* "只数攻击牌"靠 `event.bool(card.hasTag.attack)` ⇒ 拿 Skill 去打必须**不动**那个计数器，
  否则"每 3 张攻击"会退化成"每 3 张牌"。这一条是 tag 门的**唯一边界判据**；
* Pen Nib 的翻倍时机是"第 9 张挂、第 10 张吃" ⇒ 判据要在**第 10 张**上看到双倍，并且第 11 张
  回到单倍（否则不是"一次性"，而是"从此双倍"）。

## 夹具

一场对 `enc_cultist` 的战斗，牌组全 `strike`（攻击）或全 `defend`（技能），
并给英雄塞够能量/牌 —— 因为"打 10 张"需要跨过正常的一回合 3 能量 / 5 张手牌。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §261：**满能量时"加能量"必须真的加**（参考的 `CanExceedMax`）。'''

WASM_TESTS = r'''    /// §262：七件"每第 N 张某类型牌"的遗物 —— 真的打牌。
    ///
    /// 一条测试覆盖七件，因为它们的规则形状是**同一个**（`CardPlayed` + 自己的模 N 计数器），
    /// 而每条的内部判据不同：三条挂在"第 3 张攻击"上，一条挂"第 3 张技能"（tag 门的反面），
    /// 两条挂"第 10 张"，Pen Nib 还多一条"翻倍只持续一次"。
    #[test]
    fn the_every_nth_card_relics_count_the_right_kind_of_card() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一场战斗：牌组全 `strike`（攻击，6 伤害）或全 `defend`（技能），对手取 Gremlin Nob
        // （82 HP ⇒ 挨得住 10 次攻击，不会中途被打死而改变后面的判据）。
        let session_for = |card: &'static str, carrier: &str, seed: i32, enemy: &str| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, enemy, 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(carrier)
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
                .expect("apply the carrier");
            let standard = standard_turn_config().expect("standard turn config");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };

        // 打一张手牌（按 tag 挑），然后**排空队列** —— 触发器就在排空时跑。
        let play_one = |tag: &str| -> usize {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let slot_of = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .find(|slot| {
                    session
                        .state
                        .card(*slot)
                        .map(|card| {
                            content.card_has_tag(card.definition_id.as_str(), tag) == Some(true)
                        })
                        .unwrap_or(false)
                })
                .unwrap_or_else(|| panic!("no `{tag}` card in hand"));
            let before = hand_len();
            rd_core::play::play_card(
                &mut session.state,
                Some(&content),
                &rd_core::play::PlayRequest::new(hero, slot_of, None),
            )
            .expect("play the card");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
            before
        };
        // 手牌空了就补 —— 判据关心的是"打了几张"，不是"一回合能不能打这么多"。
        let top_up = || {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DrawCards {
                    owner: cid_in("hero"),
                    count: 10,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("draw");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainResource {
                    target: Some(cid_in("hero")),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 50,
                    default_max: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("energy");
        };
        let status_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(0, |c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum()
                })
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
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| c.health_current)
        };

        // ---- Kunai：第 3 张攻击才 +1 敏捷（第 2 张不给）。
        session_for("strike", "standard.kunai", 61, "enc_gremlin_nob");
        top_up();
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 0, "Kunai: after 1 attack");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 0, "Kunai: after 2 attacks");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 1, "Kunai: every 3rd attack");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 1, "Kunai: the 4th gives nothing");
        take_session();

        // ---- Shuriken：同上，但给力量。**技能的 3 张不算**（tag 门的反面）。
        session_for("defend", "standard.shuriken", 62, "enc_gremlin_nob");
        top_up();
        for n in 1..=3 {
            play_one("skill");
            assert_eq!(
                status_stacks("standard.strength"),
                0,
                "Shuriken: 3 skills still give nothing (it counts Attacks, #{n})"
            );
        }
        take_session();

        // ---- Ornamental Fan：第 3 张攻击 +4 格挡。
        session_for("strike", "standard.ornamental_fan", 63, "enc_gremlin_nob");
        top_up();
        let before = block();
        play_one("attack");
        play_one("attack");
        // 攻击牌自己能给格挡吗？`strike` 不能，所以这里的差值只可能来自遗物。
        assert_eq!(block(), before, "Ornamental Fan: no Block before the 3rd attack");
        play_one("attack");
        assert_eq!(block(), before + 4, "Ornamental Fan: 3rd attack ⇒ +4 Block");
        take_session();

        // ---- Letter Opener：第 3 张**技能**对所有敌人 5 伤害。
        session_for("defend", "standard.letter_opener", 64, "enc_gremlin_nob");
        top_up();
        let before = enemy_hp();
        play_one("skill");
        play_one("skill");
        assert_eq!(enemy_hp(), before, "Letter Opener: nothing before the 3rd Skill");
        play_one("skill");
        assert_eq!(enemy_hp(), before - 5, "Letter Opener: 3rd Skill ⇒ 5 damage to ALL");
        take_session();

        // ---- Nunchaku：第 10 张攻击 +1 能量。
        session_for("strike", "standard.nunchaku", 65, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("attack");
        }
        let energy_before = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        // 第 10 张：`strike` 花 1 点，遗物给 1 点 ⇒ 净 0。
        play_one("attack");
        let energy_after = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        assert_eq!(
            energy_after, energy_before,
            "Nunchaku: the 10th attack's +1 Energy cancels its own 1-cost"
        );
        take_session();

        // ---- Ink Bottle：第 10 张**任何**牌抽 1 张（这里用技能牌，证明它不看类型）。
        session_for("defend", "standard.ink_bottle", 66, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("skill");
        }
        let before = hand_len();
        play_one("skill");
        // 打掉 1 张、抽回 1 张 ⇒ 手牌数**不变**（前 9 张每次都少 1）。
        assert_eq!(hand_len(), before, "Ink Bottle: the 10th card draws 1 back");
        take_session();

        // ---- Pen Nib：第 10 张攻击**双倍伤害**，第 11 张回到单倍。
        session_for("strike", "standard.pen_nib", 67, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("attack");
        }
        assert_eq!(
            status_stacks("standard.double_damage"),
            1,
            "Pen Nib: the doubling is armed after the 9th attack"
        );
        let before = enemy_hp();
        play_one("attack");
        assert_eq!(
            before - enemy_hp(),
            12,
            "Pen Nib: the 10th attack deals 12, not 6"
        );
        assert_eq!(
            status_stacks("standard.double_damage"),
            0,
            "Pen Nib: the doubling is spent by that same attack"
        );
        let before = enemy_hp();
        play_one("attack");
        assert_eq!(
            before - enemy_hp(),
            6,
            "Pen Nib: the 11th attack is back to single damage"
        );
        let _ = hero_hp();
        take_session();
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_every_nth_card_relics_count_the_right_kind_of_card' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    # 接线判据（rd-run）：七件各挂自己的载体
    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §261：五件"战斗开始类"遗物的**接线**。'''
    tests = r'''    /// §262：七件"每第 N 张某类型牌"的**接线**。
    ///
    /// 逐条比状态 id：这七件全是 1 层、全走 `StartCombatStatus`，所以"抄了邻居的状态 id"
    /// 只有逐条比才看得出来（这个仓库已经踩过两次，§186 / §260）。
    #[test]
    fn the_every_nth_card_relics_wire_their_own_carrier() {
        let carrier = [
            ("kunai", "standard.kunai"),
            ("shuriken", "standard.shuriken"),
            ("ornamental_fan", "standard.ornamental_fan"),
            ("letter_opener", "standard.letter_opener"),
            ("nunchaku", "standard.nunchaku"),
            ("ink_bottle", "standard.ink_bottle"),
            ("pen_nib", "standard.pen_nib"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

'''
    assert src.count(anchor) == 1
    assert 'the_every_nth_card_relics_wire_their_own_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, tests + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
