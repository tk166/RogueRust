"""§323 wasm 端到端：`Masked Bandits` 的 `[Fight!]` 真的开出**三名**敌人。

这一层必须测的理由：事件池名 → `EncounterTables.MaskedBandits` 的跳表是**字面量**
（`content.rs` 的两张 hop 表），而 `enc_masked_bandits` 是三名敌人的**组合** ——
任何一环写错都只在"点下去之后"才炸，而且屏幕上看不出来（战斗照常开始，只是少一个人）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'

TESTS = '''    /// §323：`Masked Bandits` 的 `[Fight!]` —— 三名 bandit（Pointy / Romeo / Bear）真的上场。
    #[test]
    fn masked_bandits_fight_brings_three_named_bandits() {
        let mut seed_found = None;
        for seed in 0..2000 {
            if !walk_until_unknown(seed) {
                continue;
            }
            if rd_run_begin_node() != 0 {
                continue;
            }
            if run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event("masked_bandits", "masked_bandits")
                .is_err()
            {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no `?` room in 2000 seeds");
        // 0 = `[Pay]`、1 = `[Fight!]`。
        assert_eq!(rd_run_choose(1), 0, "seed {seed}: Fight! -- {}", run_error_text());
        assert_eq!(
            rd_run_event_fight(),
            1,
            "seed {seed}: wiki says this fight is **not** an elite"
        );
        assert_eq!(rd_run_fight_begin(), 0, "seed {seed}: {}", run_error_text());
        let session = fight_slot().as_ref().expect("a fight");
        let names: Vec<&str> = (0..session.state.enemy_count())
            .filter_map(|slot| session.state.enemy(slot))
            .map(|enemy| enemy.id())
            .collect();
        assert_eq!(names.len(), 3, "seed {seed}: three bandits, got {names:?}");
        assert_eq!(
            names,
            vec!["pointy", "romeo", "bear"],
            "seed {seed}: the roster order is the encounter's"
        );
    }

'''

ANCHOR = """    /// §322：`Pleading Vagrant` 的 `[Rob]`"""


def main():
    t = io.open(WASM, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn masked_bandits_fight_brings_three_named_bandits' not in t, 'already patched'
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS + ANCHOR))
    print('wasm masked_bandits test inserted')


main()
