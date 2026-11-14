"""§395：用**真实出牌路径**复现"史莱姆老大不分裂"。

玩家报告 + 存档回放显示：他们**死在**史莱姆老大手里（floor 16 / node 100 / health 0），
而 Boss 从头到尾没分裂过。

之前那条 `the_slime_boss_splits_into_two_large_slimes_at_half_health` 用的是
`exec::resolve_damage` + `host.try_resolve_pending_queues`（**手搓**的两步）。
真实路径是 `rd_env_step` → `step_play` → `run_fight` → `play::try_play_card` →
`host.resolve_pending_queues` —— 中间多一层。所以这条测试必须**出牌**。

判据：把 Boss 打到 50% 以下（用一张大伤害牌，不够就多打几轮），场上必须出现
`acid_slime_l` 与 `spike_slime_l`，且 Boss 不在场上了。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''    /// §385：三哨兵的相位是 **1+2**（中间的从 Beam 起手）。'''
assert t.count(ANCHOR) == 1

BLOCK = '''    /// §395：**真实出牌路径**下，史莱姆老大也要在 50% 时分裂。
    ///
    /// 上面那条 `the_slime_boss_splits_into_two_large_slimes_at_half_health` 是**手搓**的
    /// （`exec::resolve_damage` + `host.try_resolve_pending_queues`）。真实路径多一层：
    /// `rd_env_step` → `step_play` → `run_fight` → `play::try_play_card` →
    /// `host.resolve_pending_queues`。玩家是在**后者**里遇到"不分裂"的（存档回放：他死在 Boss
    /// 手里，Boss 一次都没分裂），所以判据必须走后者 —— 否则"手搓能过、真打不能"永远测不出来。
    #[test]
    fn the_slime_boss_splits_when_damaged_through_the_play_path() {
        // 一副只有打击的牌组：一次 6 点，够我们把血量一格一格推下去。
        static DECK: [DeckEntry<'static>; 10] = [
            DeckEntry::plain("strike"), DeckEntry::plain("strike"), DeckEntry::plain("strike"),
            DeckEntry::plain("strike"), DeckEntry::plain("strike"), DeckEntry::plain("strike"),
            DeckEntry::plain("strike"), DeckEntry::plain("strike"), DeckEntry::plain("strike"),
            DeckEntry::plain("strike"),
        ];
        let mut session = build_session_at(7, "enc_slime_boss", 80, Some(&DECK), 0, 0)
            .expect("the slime boss builds");
        let boss = rd_core::state::CombatantId::new("slime_boss").expect("id");
        // 直接把它压到 50% 之上一点点（80/140），剩下的用**真牌**打过去。
        {
            let combatant = session.state.combatant_mut(&boss).expect("the boss");
            combatant.health_current = 76;
        }
        session.reobserve_after_external_change();

        let mut split = false;
        for step in 0..80 {
            if session.state.combatant(&boss).is_none() {
                split = true;
                break;
            }
            let actions = session.actions.clone();
            let Some(play) = actions.iter().find(|action| action.kind == ACTION_PLAY).copied() else {
                // 没牌可出就过一轮。
                if session.step_end_turn().is_err() {
                    break;
                }
                continue;
            };
            if session.step_play(play.arg0.max(0) as usize, play.arg1).is_err() {
                break;
            }
            let _ = step;
        }
        assert!(
            split,
            "the boss must split once its HP crosses 50% — even through the real play path"
        );
        let mut acid = false;
        let mut spike = false;
        for combatant in session.state.combatants() {
            let raw = combatant.id.as_str();
            let definition = raw.split('#').next().unwrap_or(raw);
            if definition == "acid_slime_l" {
                acid = true;
            }
            if definition == "spike_slime_l" {
                spike = true;
            }
        }
        assert!(acid, "1 Acid Slime (L) must be on the field");
        assert!(spike, "1 Spike Slime (L) must be on the field");
    }

    /// §385：三哨兵的相位是 **1+2**（中间的从 Beam 起手）。'''

t = t.replace(ANCHOR, BLOCK)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('真实路径测试已加')
