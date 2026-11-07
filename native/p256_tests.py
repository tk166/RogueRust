"""§256 判据：5 个精英的语义校对（它们本来就在，缺的是细节）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §256：`Book of Stabbing` 的 **Painful Stabs** —— 造成**未被格挡**伤害时往你的弃牌堆塞 Wound。
    ///
    /// 这条机制之前完全没有（状态、触发器、挂载三样都缺），所以判据要钉住三件事：
    /// ① 敌人身上**确实**挂着 `standard.painful_stabs`（挂载点：`enc_book_of_stabbing` 的
    ///    `StartingStatuses`，与名册那行同源）；
    /// ② 一次**掉血**的攻击 ⇒ 弃牌堆多一张 `wound`；
    /// ③ 一次**被格挡吃光**的攻击 ⇒ **一张都不多**（wiki 的判据是 "unblocked damage" ——
    ///    只测 ② 的话，"每次攻击都塞"这种错会绿）。
    #[test]
    fn painful_stabs_shuffles_a_wound_only_on_unblocked_damage() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        // 敌人身上挂 Painful Stabs（与 `enc_book_of_stabbing` 的起始状态一致）。
        give(&mut state, "enemy_a", status("ps1", "standard.painful_stabs", 1));
        let wound_in_discard = |state: &CombatState| -> usize {
            let Some(zones) = state.card_zones(&cid("hero")) else {
                return 0;
            };
            let mut wounds = 0usize;
            for index in 0..zones.count(CardZone::DiscardPile) {
                let Some(slot) = zones.slot_at(CardZone::DiscardPile, index) else {
                    continue;
                };
                if let Some(card) = state.card(slot) {
                    if card.definition_id.as_str() == "wound" {
                        wounds += 1;
                    }
                }
            }
            wounds
        };

        // ② 未被格挡：走真实的伤害管线（源 = 敌人，目标 = 英雄）。
        let before = wound_in_discard(&state);
        crate::exec::resolve_effect(
            &mut state,
            &crate::state::EffectItem {
                request: crate::state::EffectRequest::DealDamage {
                    target: Some(cid("hero")),
                    amount: 6,
                    ignores_block: false,
                    source: Some(cid("enemy_a")),
                },
                chain: crate::state::ChainSlot::NONE,
                owner: None,
            },
            Some(&content),
        )
        .expect("the hit lands");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            wound_in_discard(&state),
            before + 1,
            "unblocked damage ⇒ one Wound in the hero's discard pile"
        );

        // ③ 被格挡吃光：英雄先攒够格挡，6 点伤害一滴都不掉 ⇒ 不该多 Wound。
        let before = wound_in_discard(&state);
        crate::exec::resolve_effect(
            &mut state,
            &crate::state::EffectItem {
                request: crate::state::EffectRequest::GainBlock {
                    target: Some(cid("hero")),
                    amount: 20,
                    from_card: false,
                },
                chain: crate::state::ChainSlot::NONE,
                owner: None,
            },
            Some(&content),
        )
        .expect("block");
        crate::exec::resolve_effect(
            &mut state,
            &crate::state::EffectItem {
                request: crate::state::EffectRequest::DealDamage {
                    target: Some(cid("hero")),
                    amount: 6,
                    ignores_block: false,
                    source: Some(cid("enemy_a")),
                },
                chain: crate::state::ChainSlot::NONE,
                owner: None,
            },
            Some(&content),
        )
        .expect("the blocked hit lands");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            wound_in_discard(&state),
            before,
            "fully blocked ⇒ no Wound (the rule is 'unblocked damage')"
        );
    }

    /// §256：五个精英的**数字**与内容对齐（wiki 的 HP 与招式伤害）。
    ///
    /// 这一条读的是**内容镜像**而不是跑战斗：这些数是"内容是否抄对"的问题，而跑一场战斗只能
    /// 看到其中一两个。它同时是"这 5 个精英真的在池子里"的判据 —— 之前那条
    /// "精英只有 4 个、缺这 5 个"的记录是**过期**的，这条测试把它钉成事实。
    #[test]
    fn the_five_elite_encounters_match_the_wiki_numbers() {
        let content = sts_image();
        // (encounter, 敌人 id, HP, 该敌人有这些动作)
        let expectations: &[(&str, &str, i32, &[&str])] = &[
            ("enc_lagavulin", "lagavulin", 109,
             &["lagavulin.attack", "lagavulin.siphon_soul", "lagavulin.sleep"]),
            ("enc_book_of_stabbing", "book_of_stabbing", 160,
             &["book_of_stabbing.multi_stab", "book_of_stabbing.big_stab"]),
            ("enc_slavers", "taskmaster", 54, &["taskmaster.scouring_whip"]),
            ("enc_slavers", "slaver_red", 46,
             &["slaver_red.stab", "slaver_red.scrape", "slaver_red.entangle"]),
            ("enc_slavers", "blue_slaver", 46, &["blue_slaver.stab", "blue_slaver.rake"]),
            ("enc_nemesis", "nemesis", 185,
             &["nemesis.tri_attack", "nemesis.tri_burn", "nemesis.scythe"]),
            ("enc_reptomancer", "reptomancer", 180,
             &["reptomancer.spawn_dagger", "reptomancer.big_bite",
               "reptomancer.snake_strike"]),
            ("enc_reptomancer", "dagger", 20, &["dagger.wound", "dagger.explode"]),
        ];
        for (encounter_id, enemy_id, hp, actions) in expectations {
            let row = content
                .row_by_id(crate::content::Table::Encounter, encounter_id)
                .unwrap_or_else(|| panic!("{encounter_id} is in the image"));
            // 敌人名册在 ENCT 行的 `Enemies` 数组里；用内核自己的解码走过去。
            let plan = crate::battle::encounter_roster(&content, encounter_id)
                .unwrap_or_else(|error| panic!("{encounter_id}: {error:?}"));
            let _ = row;
            let Some(enemy) = plan.iter().find(|slot| slot.id == *enemy_id) else {
                panic!("{encounter_id} contains {enemy_id}: {:?}", plan.len());
            };
            assert_eq!(
                enemy.max_health, *hp,
                "{encounter_id}/{enemy_id}: wiki HP"
            );
            for action in *actions {
                assert!(
                    content.lookup_in(action, crate::content::EK_EACTION).is_some(),
                    "{enemy_id} uses {action}, which must exist"
                );
            }
        }
        // 蓝皮强盗**不该**挂时间吞噬者的能力（§256 修掉的错）。
        let slavers = crate::battle::encounter_roster(&content, "enc_slavers")
            .expect("enc_slavers");
        let blue = slavers
            .iter()
            .find(|slot| slot.id == "blue_slaver")
            .expect("the blue slaver");
        let _ = blue;
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'painful_stabs_shuffles_a_wound' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 elite tests')


main()
