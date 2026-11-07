"""§278：A15 判据改成走**两段**——第一段拿遗物，第二段验三选一的百分比。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

OLD_START = '''        const DAMAGE_CODE: i32 = 3;
        const RELIC_CODE: i32 = 10;'''

OLD_END = '''                "the legacy accessor is the head of the list"
            );
        }
    }'''

NEW = '''        const DAMAGE_PCT_CODE: i32 = 11;
        const MAX_HP_PCT_CODE: i32 = 12;
        const RELIC_CODE: i32 = 10;
        const CURSE_CODE: i32 = 9;
        for level in [0u8, 14, 15, 20] {
            let mut state = rd_run::state::RunState::new_with_ascension(
                7,
                80,
                0,
                &["strike"; 5],
                level,
            )
            .expect("a run");
            assert_eq!(state.ascension(), level, "the run knows its level");
            state.begin_event("golden_idol", "golden_idol").expect("open the event");
            *run_slot() = Some(RunSession {
                state: Box::new(state),
                error: String::new(),
                elite_fight: false,
                boss_fight: false,
                in_fight: false,
                journal: Vec::new(),
                head: std::format!("RDR1,S,7,{level},{}", content_pin_text()),
                replaying: false,
                replay_checked: 0,
                replay_diverged: 0,
                hash_failed: false,
            });

            // ── 第一段：`Take it` 只有**一条**效果（遗物），而且它把玩家带去巨石那段。
            assert_eq!(
                rd_run_event_effect_count(0),
                1,
                "A{level}: taking the idol is one effect now (the curse lives in the next step)"
            );
            assert_eq!(rd_run_event_effect_at(0, 0), RELIC_CODE, "the relic");
            assert_eq!(
                rd_run_event_effect(0),
                rd_run_event_effect_at(0, 0),
                "the legacy accessor is the head of the list"
            );
            assert_eq!(rd_run_choose(0), 0, "A{level}: take the idol");
            // ★ 房间**没有**结算：还有一段。
            assert_eq!(rd_run_pending(), 5, "A{level}: the event is still open");
            assert_eq!(rd_run_node_resolved(), 0, "A{level}: nothing is settled yet");
            assert_eq!(
                rd_run_event_option_count(),
                3,
                "A{level}: the boulder step is a **three**-way choice"
            );

            // ── 第二段：Smash 按最大 HP 的百分比，A15 换的是**另一条效果**。
            let want = if level >= 15 { 35 } else { 25 };
            assert_eq!(rd_run_event_effect_at(1, 0), DAMAGE_PCT_CODE, "Smash is a percentage");
            assert_eq!(
                rd_run_event_amount_at(1, 0),
                want,
                "A{level}: Smash's percentage must be {want}% (wiki: 25% / A15 35%)"
            );
            // Hide 也一样，只是它扣的是**上限**。
            let want_hide = if level >= 15 { 10 } else { 8 };
            assert_eq!(rd_run_event_effect_at(2, 0), MAX_HP_PCT_CODE, "Hide is a percentage");
            assert_eq!(
                rd_run_event_amount_at(2, 0),
                want_hide,
                "A{level}: Hide's percentage must be {want_hide}% (wiki: 8% / A15 10%)"
            );
            // Outrun 的诅咒在两个档位上**相同**（wiki 没有给它 A15 变体）。
            assert_eq!(rd_run_event_effect_at(0, 0), CURSE_CODE, "Outrun is the curse");
            assert_eq!(rd_run_event_effect_count(0), 1, "one curse, no A15 variant");

            // ── 走完第二段，房间这才结算。
            let hp_max = rd_run_observe(3);
            let hp = rd_run_observe(2);
            assert_eq!(rd_run_choose(1), 0, "A{level}: smash the boulder");
            assert_eq!(rd_run_observe(3), hp_max, "A{level}: max HP is untouched by Smash");
            assert_eq!(
                rd_run_observe(2),
                hp - (hp_max * want / 100),
                "A{level}: Smash takes floor(max HP × {want}%)"
            );
            assert_eq!(rd_run_node_resolved(), 1, "A{level}: the room paid once");
        }
    }'''


def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END, start) + len(OLD_END)
    body = s[start:end]
    assert 'A15' in body or 'want_second' in body, 'wrong region'
    s = s[:start] + NEW + s[end:]
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('A15 test now walks both steps')


main()
