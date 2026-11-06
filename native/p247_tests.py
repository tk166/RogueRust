"""§247 判据：Mind Blast（zoneCount）/ Enlightenment（Mode: Set）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §246：`Thinking Ahead` —— **先抽 2 张，再问**'

TESTS = r'''    /// §247：`Mind Blast` —— 伤害 = **抽牌堆的张数**（不是手牌、不是牌组）。
    ///
    /// 三段：① 抽牌堆有 7 张 ⇒ 打 7；② 抽牌堆**空** ⇒ 打 0（`zoneCount` 的"空"是合法答案，
    /// 不是错误）；③ 张数**在出牌那一刻**读 —— 同一张牌在两局里抽牌堆不同、伤害就不同
    /// （写死成常量也会让 ① 过，所以 ②③ 一起才有意义）。
    #[test]
    fn mind_blast_scales_with_the_draw_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let dealt = |draw_pile: usize| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            for index in 0..draw_pile {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_p{index}"), "defend", None);
            }
            give_card(&mut state, "hero", CardZone::Hand, "card_x", "mind_blast", None);
            let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
            )
            .expect("mind blast is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            200 - health(&state, "enemy_a")
        };

        assert_eq!(dealt(7), 7, "7 cards in the draw pile ⇒ 7 damage");
        assert_eq!(dealt(0), 0, "an empty draw pile ⇒ 0 damage (and no error)");
        assert_eq!(dealt(11), 11, "and it re-reads the pile every time");
    }

    /// §247：`Enlightenment` —— 把**手牌里每一张**的价格**设**成 1（不是"减 1"）。
    ///
    /// 判据落在**实际付款**上（不是"标记写进去了"）：手里放一张 2 费与一张 0 费的牌，
    /// 打完 Enlightenment 后 2 费那张只收 1 点，而 **0 费那张仍然是 0**。
    ///
    /// 第三段是 `Mode: Set` 存在的全部理由：如果实现成 `Add`（累加），"设成 1" 在 0 费牌上会把它
    /// 抬成 1 —— 那不是"减到 1"，是"加 1"。
    #[test]
    fn enlightenment_sets_hand_costs_to_one() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let energy_left = |card_id: &str, cost_two: bool| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(
                    crate::state::ResourceId::new("standard.energy").expect("energy"),
                    9,
                    Some(99),
                )
                .expect("the pool accepts a bigger cap");
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            // 手牌：一张 2 费（`bash`）、一张 0 费（`flex` 是 0 费）。
            if cost_two {
                give_card(&mut state, "hero", CardZone::Hand, "card_big", "bash", None);
            } else {
                give_card(&mut state, "hero", CardZone::Hand, "card_big", "flex", None);
            }
            give_card(&mut state, "hero", CardZone::Hand, "card_en", "enlightenment", None);
            let enlighten = crate::state::CardInstanceId::new("card_en").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), enlighten, Some(cid("enemy_a"))),
            )
            .expect("enlightenment is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");

            let big = crate::state::CardInstanceId::new("card_big").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), big, Some(cid("enemy_a"))),
            )
            .expect("the discounted card is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let _ = card_id;
            energy_of(&state, "hero")
        };

        assert_eq!(energy_left("bash", true), 8, "a 2-cost card now costs 1");
        assert_eq!(
            energy_left("flex", false),
            9,
            "and a 0-cost card stays at 0 -- `Set`, not `Add`"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'mind_blast_scales_with' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 tests')


main()
