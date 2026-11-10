"""§322 wasm 端到端：四条事件**真的**能在 ABI 上走完，且可观察结果对。

为什么要在这一层再测一遍：`relic_random` 是**wasm 解析**的（运行层不认识遗物池），
`gold_cost` 与 `remove_all` / `card:` 张数是运行层的。只测一侧会漏"两边各自对、合起来不对"。

四条各挑最"有信息"的那个选项：
- `pleading_vagrant` `[Rob]`：`relic_random` + `curse:shame` + `Next` 段链
- `old_beggar` `[Offer 75 Gold]`：`gold_cost` + **改牌问句**（`remove_card`）+ `MinGold` 门槛外
- `vampires` `[Accept]`：`remove_all` + **5 张** `bite` + 30% 上限
- `council_of_ghosts` `[Accept]`：5 张 `apparition` + 50% 上限
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'

ANCHOR = """    /// §321：`blocked_heals` 的 wasm 侧不在这一层 —— 见 `docs/port-plan.md`。"""

if False:
    pass

TESTS = '''    /// §322：`Pleading Vagrant` 的 `[Rob]` —— 随机遗物 + `Shame` + 走到下一段。
    #[test]
    fn pleading_vagrant_rob_gives_a_relic_and_a_curse_then_moves_on() {
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
                .begin_event("pleading_vagrant", "pleading_vagrant")
                .is_err()
            {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no `?` room in 2000 seeds");

        let relics_before = run_slot().as_ref().expect("a run").state.relics().len();
        let deck_before = rd_run_deck_count();
        assert_eq!(rd_run_event_option_count(), 3, "seed {seed}: three options");
        assert_eq!(rd_run_choose(1), 0, "seed {seed}: Rob -- {}", run_error_text());

        let state = &run_slot().as_ref().expect("a run").state;
        assert_eq!(state.relics().len(), relics_before + 1, "seed {seed}: a random relic");
        assert_eq!(rd_run_deck_count(), deck_before + 1, "seed {seed}: Shame went in");
        // `[Rob]` 的 `Next` 是一段"Leave"，所以事件**还没**收尾。
        assert_eq!(rd_run_event_option_count(), 1, "seed {seed}: the leave screen");
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: {}", run_error_text());
        assert!(run_slot().as_ref().expect("a run").state.node_resolved(),
                "seed {seed}: the room settles after Leave");
    }

    /// §322：`Old Beggar` 的 `[Offer 75 Gold]` —— 付 75、然后**问玩家要删哪一张**。
    #[test]
    fn old_beggar_takes_the_gold_and_asks_which_card() {
        let mut seed_found = None;
        for seed in 0..2000 {
            if !walk_until_unknown(seed) {
                continue;
            }
            if rd_run_begin_node() != 0 {
                continue;
            }
            let ok = run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event("old_beggar", "old_beggar")
                .is_ok();
            if !ok {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no `?` room in 2000 seeds");
        // 80 金币的局：付得起 75。
        let gold_before = run_slot().as_ref().expect("a run").state.gold();
        assert!(gold_before >= 75, "seed {seed}: the fixture starts with {gold_before} gold");
        let deck_before = rd_run_deck_count();
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(
            run_slot().as_ref().expect("a run").state.gold(),
            gold_before - 75,
            "seed {seed}: 75 gold is gone"
        );
        assert_eq!(
            run_slot().as_ref().expect("a run").state.pending(),
            rd_run::state::Pending::EventCard,
            "seed {seed}: it asks which card"
        );
        assert_eq!(rd_run_pick_event_card(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(rd_run_deck_count(), deck_before - 1, "seed {seed}: one card removed");
    }

    /// §322：`Vampires` 的 `[Accept]` —— 删掉**所有**打击、给 **5** 张 Bite、失去 30% 上限。
    #[test]
    fn vampires_swaps_every_strike_for_five_bites() {
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
                .begin_event("vampires", "vampires")
                .is_err()
            {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no `?` room in 2000 seeds");
        let before = *run_slot().as_ref().expect("a run").state;
        let strikes_before = before
            .deck()
            .iter()
            .filter(|card| card.as_str().trim_end_matches('+') == "strike")
            .count();
        assert!(strikes_before > 0, "seed {seed}: the fixture has Strikes");
        // 0 = `[Offer: Blood Vial]`（没有血瓶时**不可选**）、1 = `[Accept]`、2 = `[Refuse]`。
        assert_eq!(rd_run_choose(1), 0, "seed {seed}: Accept -- {}", run_error_text());
        let after = &run_slot().as_ref().expect("a run").state;
        assert_eq!(
            after
                .deck()
                .iter()
                .filter(|card| card.as_str().trim_end_matches('+') == "strike")
                .count(),
            0,
            "seed {seed}: every Strike is gone"
        );
        assert_eq!(
            after.deck().iter().filter(|card| card.as_str() == "bite").count(),
            5,
            "seed {seed}: five Bites"
        );
        assert_eq!(
            after.health_max(),
            before.health_max() - before.health_max() * 30 / 100,
            "seed {seed}: 30% of max HP"
        );
    }

    /// §322：`Council of Ghosts` 的 `[Accept]` —— 5 张 Apparition + 50% 上限。
    #[test]
    fn council_of_ghosts_gives_five_apparitions() {
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
                .begin_event("council_of_ghosts", "council_of_ghosts")
                .is_err()
            {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no `?` room in 2000 seeds");
        let before = *run_slot().as_ref().expect("a run").state;
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: Accept -- {}", run_error_text());
        let after = &run_slot().as_ref().expect("a run").state;
        assert_eq!(
            after.deck().iter().filter(|card| card.as_str() == "apparition").count(),
            5,
            "seed {seed}: five Apparitions"
        );
        assert_eq!(
            after.health_max(),
            before.health_max() - before.health_max() * 50 / 100,
            "seed {seed}: half of max HP"
        );
    }

'''


def main():
    t = io.open(WASM, encoding='utf-8').read()
    anchor = """    fn an_event_fight_begins_and_settles_as_an_elite() {"""
    assert t.count(anchor) == 1, 'anchor'
    assert 'fn vampires_swaps_every_strike_for_five_bites' not in t, 'already patched'
    # 插在 `#[test]` 那一行之前。
    marker = '    #[test]\n' + anchor
    assert t.count(marker) == 1, 'marker'
    t = t.replace(marker, TESTS + '    #[test]\n' + anchor)
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
    print('wasm event tests inserted')


main()
