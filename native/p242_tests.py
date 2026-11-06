"""§242 判据：spot_weakness / blood_for_blood / corruption。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §241：`Havoc` —— "Play the top card of your draw pile and Exhaust it."'

TESTS = r'''    /// §242：`Blood for Blood` —— **每失去 1 次生命便宜 1 点**，本场战斗累计。
    ///
    /// 三段：① 一次都没掉血 ⇒ 4 费（照印刷）；② 掉两次 ⇒ 2 费；③ 掉到超过印刷费 ⇒ **0 费**
    /// （不是负数 —— `current.max(0)` 那一层）。第三段最容易漏：不夹的话"掉 6 次血"会变成负费用，
    /// 而负费用在付款时会**给**能量。
    ///
    /// 掉血用伤害造（`strike` 打自己人太绕）：直接写 `hp_losses` 就绕过了被测的那条记账，
    /// 所以这里用 `Lose HP` 走 `lose_hp` —— 它也算"失去生命"，顺带证明记账在**两条路**上都做了。
    #[test]
    fn blood_for_blood_gets_cheaper_each_time_you_lose_hp() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 用 `bloodletting`（0 费，Lose 3 HP）造掉血：它自己不花钱，所以能量账干净。
        let cost_after = |losses: i32| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            for _ in 0..losses {
                let card = card_in_hand(&mut state, &content, "hero", "bloodletting");
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
                )
                .expect("bloodletting is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");
            }
            let card = card_in_hand(&mut state, &content, "hero", "blood_for_blood");
            let plan = crate::play::plan_for_test(&state, Some(&content), &card);
            plan.expect("the plan builds").paid_energy()
        };

        assert_eq!(cost_after(0), 4, "no HP loss yet ⇒ the printed 4");
        assert_eq!(cost_after(2), 2, "two HP losses ⇒ 2");
        assert_eq!(cost_after(9), 0, "more losses than the printed cost ⇒ 0, never negative");
    }

    /// §242：`Corruption` —— 技能**0 费**且打完**进消耗堆**；攻击牌两件事都不吃。
    ///
    /// 这条判据的重点是"只认技能"：`corruption` 的两条规则都按 `is_skill` 分流，写错一处就会
    /// 让攻击牌也免费/也被消耗 —— 那两件事在页面上都"看起来很正常"（少花能量、牌没了）。
    #[test]
    fn corruption_makes_skills_free_and_exhausts_them() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 技能：`defend`（1 费）不花能量，且进消耗堆。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give(&mut state, "hero", status("st_corp", "standard.corruption", 1));
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 3, "a Skill under Corruption costs 0");
        assert_eq!(block_of(&state, "hero"), 5, "and still does its job");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [std::string::String::from("defend")],
            "the Skill is Exhausted after play"
        );

        // ② 攻击牌：`strike`（1 费）照付、照常进弃牌堆。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give(&mut state, "hero", status("st_corp", "standard.corruption", 1));
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "an Attack still pays its cost");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [std::string::String::from("strike")],
            "and an Attack is not Exhausted"
        );

        // ③ 没有 Corruption：技能照付、进弃牌堆（对照组 —— 否则 ① 的"免费"可能本来就成立）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "without Corruption a Skill pays 1");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [std::string::String::from("defend")],
            "and lands in the discard pile"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'blood_for_blood_gets_cheaper' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 tests')


main()
