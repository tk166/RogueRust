"""§324 wasm 端到端：`augmenter` 三个选项都在 ABI 上真的生效。

- `[Test J.A.X.]`：牌组 +1，且那张是 `jax`；
- `[Become Test Subject]`：`pickup_change = Transform`、`pickup_picks = 2`（欠账通道），
  然后 `rd_run_pickup_card` 两次各变一张，牌组**尺寸不变**；
- `[Ingest Mutagens]`：遗物进包，`combat_bonus` 挂上 `standard.mutagenic_strength`。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'
ANCHOR = """    /// §323：`Masked Bandits` 的 `[Fight!]`"""

TESTS = '''    /// §324：`augmenter` —— 三个选项各走一遍（`?` 房上手动开事件）。
    fn augmenter_at(seed_range: std::ops::Range<i32>) -> Option<i32> {
        for seed in seed_range {
            if !walk_until_unknown(seed) || rd_run_begin_node() != 0 {
                continue;
            }
            if run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event("augmenter", "augmenter")
                .is_ok()
            {
                return Some(seed);
            }
        }
        None
    }

    #[test]
    fn augmenter_test_jax_adds_the_card() {
        let seed = augmenter_at(0..2000).expect("no `?` room");
        let before = rd_run_deck_count();
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: Test J.A.X. -- {}", run_error_text());
        assert_eq!(rd_run_deck_count(), before + 1, "seed {seed}: one card went in");
        let state = &run_slot().as_ref().expect("a run").state;
        assert_eq!(
            state.deck()[state.deck_len as usize - 1].as_str(),
            "jax",
            "seed {seed}: it is J.A.X."
        );
    }

    #[test]
    fn augmenter_become_test_subject_owes_two_transforms() {
        let seed = augmenter_at(0..2000).expect("no `?` room");
        let before = rd_run_deck_count();
        assert_eq!(rd_run_choose(1), 0, "seed {seed}: Become Test Subject -- {}", run_error_text());
        // 欠账与 `pending` 是两条通道：事件已经收尾，选择器还欠两次。
        let session = run_slot().as_ref().expect("a run");
        assert_eq!(session.state.pending(), rd_run::state::Pending::None, "seed {seed}");
        assert_eq!(rd_run_pickup_picks(), 2, "seed {seed}: two transforms owed");
        assert_eq!(rd_run_pickup_change(), 3, "seed {seed}: the debt is `Transform` (=3)");
        assert_eq!(rd_run_pickup_card(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(rd_run_pickup_picks(), 1, "seed {seed}: one left");
        assert_eq!(rd_run_pickup_card(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(rd_run_pickup_picks(), 0, "seed {seed}: the debt is gone");
        assert_eq!(rd_run_deck_count(), before, "seed {seed}: transform keeps the size");
    }

    #[test]
    fn augmenter_ingest_mutagens_grants_its_carrier() {
        let seed = augmenter_at(0..2000).expect("no `?` room");
        let before = run_slot().as_ref().expect("a run").state.relics().len();
        assert_eq!(rd_run_choose(2), 0, "seed {seed}: Ingest Mutagens -- {}", run_error_text());
        let session = run_slot().as_ref().expect("a run");
        assert_eq!(session.state.relics().len(), before + 1, "seed {seed}: the relic is in the bag");
        let bonus = session.state.combat_bonus();
        assert!(
            (0..bonus.status_count).any(|index| bonus.statuses[index]
                .map(|entry| entry.id == "standard.mutagenic_strength")
                .unwrap_or(false)),
            "seed {seed}: +3 Strength rides `standard.mutagenic_strength`"
        );
    }

'''

ANCHOR2 = ANCHOR


def main():
    t = io.open(WASM, encoding='utf-8').read()
    assert t.count(ANCHOR2) == 1, 'anchor'
    assert 'fn augmenter_become_test_subject_owes_two_transforms' not in t, 'already patched'
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR2, TESTS + ANCHOR2))
    print('wasm augmenter tests inserted')


main()
