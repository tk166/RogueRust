"""§304：内容遗物行 + 判据。

## 判据分两层

* **rd-run**：`combat_open_choices()` 的位掩码（有/无遗物、两件同时、候选张数）。
* **rd-wasm**：真的开一场，问句自己出现、答完之后状态对（弃 2 张 → 手牌不变、弃牌 +2）、
  两件同时在时**先问 chip 再问 toolbox**、`toolbox` 拿到的牌**价格不动**（没有每副本折扣）。

## 负控要看的两件事

① 没有遗物时**不问**；② `toolbox` 不写价格（若误用 `ToHand` 会写一个 `-printed` 的折扣，
于是那张牌当回合免费 —— 而 wiki 没有这句话）。
"""
import io
import json

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'

RUN_TEST = r'''
    /// §304：两件"开战问一句"的遗物 —— 位掩码与候选张数。
    ///
    /// 位掩码而不是 `Option`：两件**可以同时在身上**，而内核一次只允许一个问题挂着
    /// （`begin_choice` 拒绝嵌套）。顺序由位的顺序定，所以同一颗种子的问句序列是确定的。
    #[test]
    fn the_combat_open_relics_are_a_bitmask_and_absent_without_the_relics() {
        let deck = ["strike", "defend"];
        let mut run = RunState::new(31, 80, 99, &deck).expect("a run");
        assert_eq!(run.combat_open_choices(), (0, 0), "no relics, no questions");

        run.push_relic("gambling_chip", &[]).expect("gambling_chip");
        assert_eq!(
            run.combat_open_choices(),
            (rd_run::state::COMBAT_OPEN_GAMBLING_CHIP, 0)
        );

        run.push_relic("toolbox", &[]).expect("toolbox");
        let (mask, offer) = run.combat_open_choices();
        assert_eq!(
            mask,
            rd_run::state::COMBAT_OPEN_GAMBLING_CHIP | rd_run::state::COMBAT_OPEN_TOOLBOX,
            "both relics are owed"
        );
        assert_eq!(offer, 3, "toolbox offers three candidates (wiki)");
    }
'''

WASM_TEST = r'''
    /// §304：`gambling_chip` —— 开战那一刻问"弃任意张，然后抽同样多张"。
    ///
    /// 判据要的三件事：① 问句**自己**出现（不是页面猜的）；② `min = 0`（wiki 的 "any number"
    /// 与 Gambler's Brew 同一句话，所以"取消"永远可用）；③ 答完之后**手牌数不变**、弃牌堆 +2、
    /// 抽牌堆 -2（弃 2 抽 2）。
    #[test]
    fn gambling_chip_asks_at_combat_start_and_discards_then_draws() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(41, 80, 80, &deck);
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("gambling_chip", &[])
            .expect("gambling_chip");
        assert_eq!(rd_run_step(0), 0, "walk onto a node");
        assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

        assert_eq!(rd_env_choice_pending(), 1, "the relic asks its question");
        assert_eq!(rd_env_choice_source(), 1, "from the hand");
        assert_eq!(rd_env_choice_kind(), 2, "discard then draw (Gambler's Brew's shape)");
        assert_eq!(rd_env_choice_min(), 0, "any number, including zero");
        let max = rd_env_choice_max();
        let hand = rd_env_choice_count();
        assert_eq!(max as i32, hand, "every card in hand is on offer");

        let (hand_before, discard_before, draw_before) = pile_counts();
        // 选前两张，确认。
        assert_eq!(rd_env_choice_pick(0, 1), 0);
        assert_eq!(rd_env_choice_pick(1, 1), 0);
        assert_eq!(rd_env_choice_confirm(), 0, "{}", run_error_text());
        assert_eq!(rd_env_choice_pending(), 0, "answered");

        let (hand_after, discard_after, draw_after) = pile_counts();
        assert_eq!(hand_after, hand_before, "discarded two, drew two");
        assert_eq!(discard_after, discard_before + 2, "two went to the discard pile");
        assert_eq!(draw_after, draw_before - 2, "two came off the draw pile");
    }

    /// §304：`toolbox` —— 三选一拿进手牌，**按它的印刷价格**（不是免费）。
    ///
    /// 后半句是这条判据的重点：如果实现误用 `ChoiceThen::ToHand` 再传 `delta = 0`，行为"看起来"
    /// 一样，但页面的文案会承诺免费；反过来传 `-printed` 就会真的免费。这里直接读那张新牌的
    /// `card_cost_delta` 标记（"没有标记" = 价格不动）。
    #[test]
    fn toolbox_offers_three_colorless_cards_and_charges_the_printed_price() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(43, 80, 80, &deck);
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("toolbox", &[])
            .expect("toolbox");
        assert_eq!(rd_run_step(0), 0, "walk onto a node");
        assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

        assert_eq!(rd_env_choice_pending(), 1, "the relic asks its question");
        assert_eq!(rd_env_choice_source(), 2, "three offered candidates");
        assert_eq!(rd_env_choice_kind(), 10, "`ToHandPrinted`: into hand, price untouched");
        assert_eq!(rd_env_choice_min(), 1);
        assert_eq!(rd_env_choice_max(), 1);
        assert_eq!(rd_env_choice_count(), 3, "three candidates (wiki)");
        // 每一张候选都得是**无色**牌（内容是 `CARD.Tags` 的事，这里用同一个来源核对）。
        let image = content();
        for index in 0..rd_env_choice_count() {
            let id = choice_option_title(index);
            assert!(
                image.card_has_tag(&id, "colorless") == Some(true),
                "`{id}` is not a colorless card"
            );
        }

        let hand_before = pile_counts().0;
        assert_eq!(rd_env_choice_pick(0, 1), 0);
        assert_eq!(rd_env_choice_confirm(), 0, "{}", run_error_text());
        assert_eq!(rd_env_choice_pending(), 0, "answered");

        let session = crate::slot().as_ref().expect("a fight");
        let hero = session.hero_id().expect("a hero");
        assert_eq!(
            pile_counts().0,
            hand_before + 1,
            "the chosen card went into the hand"
        );
        // 挑出那张新牌：它不在开局牌组里（牌组只有 strike/defend/bash）。
        let mut priced = 0;
        let mut found = false;
        for index in 0..session
            .state
            .card_zones(&hero)
            .map_or(0, |zones| zones.count(rd_core::state::CardZone::Hand))
        {
            let Some(slot) = session
                .state
                .card_zones(&hero)
                .and_then(|zones| zones.slot_at(rd_core::state::CardZone::Hand, index))
            else {
                continue;
            };
            let Some(card) = session.state.card(slot) else {
                continue;
            };
            let definition = card.definition_id.as_str();
            if definition == "strike" || definition == "defend" || definition == "bash" {
                continue;
            }
            found = true;
            for counter in card.mark_counters() {
                if counter.key.as_str() == "standard.card_cost_delta" && counter.value != 0 {
                    priced += 1;
                }
                if counter.key.as_str() == "standard.card_cost_override" {
                    priced += 1;
                }
            }
        }
        assert!(found, "a colorless card is in the hand");
        assert_eq!(priced, 0, "toolbox must not write a price (it is not free)");
    }

    /// §304：两件同时在身上 —— 先问 `gambling_chip`，答完之后 `toolbox` 的问句才出现。
    ///
    /// 内核的 `begin_choice` 拒绝嵌套，所以"两个问句"只能靠**答完一个再问下一个**。这条判据
    /// 钉住的是那条链：`rd_env_choice_confirm` 成功后必须接着问。
    #[test]
    fn both_open_relics_ask_one_question_at_a_time() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(47, 80, 80, &deck);
        {
            let run = run_slot().as_mut().expect("a run");
            run.state.push_relic("gambling_chip", &[]).expect("chip");
            run.state.push_relic("toolbox", &[]).expect("toolbox");
        }
        assert_eq!(rd_run_step(0), 0, "walk onto a node");
        assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

        assert_eq!(rd_env_choice_pending(), 1);
        assert_eq!(rd_env_choice_source(), 1, "chip first (it is the low bit)");
        assert_eq!(rd_env_choice_confirm(), 0, "answer with nothing: {}", run_error_text());

        assert_eq!(rd_env_choice_pending(), 1, "the second question follows");
        assert_eq!(rd_env_choice_source(), 2, "and it is `toolbox`");
        assert_eq!(rd_env_choice_kind(), 10);
        assert_eq!(rd_env_choice_pick(1, 1), 0);
        assert_eq!(rd_env_choice_confirm(), 0, "{}", run_error_text());
        assert_eq!(rd_env_choice_pending(), 0, "both answered");
    }
'''


def main():
    s = io.open(STATE, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s[:cut] + RUN_TEST + s[cut:])
    print('rd-run test')

    t = io.open(RUN, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t[:cut] + WASM_TEST + t[cut:])
    print('rd-wasm tests')

    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    ids = {r['Id'] for r in doc['Relics']}
    for relic, display, rarity in (('gambling_chip', 'Gambling Chip', 'Rare'),
                                   ('toolbox', 'Toolbox', 'Rare')):
        if relic not in ids:
            doc['Relics'].append({'Id': relic, 'DisplayName': display,
                                  'RunPrograms': None, 'CombatRules': None, 'Rarity': rarity})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content relics', len(doc['Relics']))

    c = io.open(CHECK, encoding='utf-8').read()
    old = '''                      # §303：`wing_boots`（运行层的地图规则）。
                      "wing_boots",'''
    assert c.count(old) == 1
    c = c.replace(old, '''                      # §303：`wing_boots`（运行层的地图规则）。
                      "wing_boots",
                      # §304：两件"开战问一句"的遗物。
                      "gambling_chip", "toolbox",''')
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(c)
    print('gate list')


main()
