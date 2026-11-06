"""§238 判据：heavy_blade 的力量倍率、feed 的 If Fatal、double_tap 的作用域、exhume。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §237：`BlockGained` 钩子'

TESTS = '''    /// §238：`Heavy Blade` —— **力量算 3（升级 5）次**，而伤害数（14）不升级。
    ///
    /// 判据看的是"力量系数"，所以三档力量各测一次：0 力量（=14）、+3 力量（=14+3×3=23）、
    /// 而升级版同一力量下是 14+3×5=29。**只测 0 力量会把倍率整条漏掉**（14 与倍率无关）。
    #[test]
    fn heavy_blade_multiplies_strength_three_or_five_times() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let play = |card_id: &str, strength: i32| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            if strength != 0 {
                give(&mut state, "hero", status("st_str", "standard.strength", strength));
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("heavy blade is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            200 - health(&state, "enemy_a")
        };

        assert_eq!(play("heavy_blade", 0), 14, "no Strength ⇒ just the printed 14");
        assert_eq!(play("heavy_blade", 3), 14 + 3 * 3, "Strength ×3");
        assert_eq!(play("heavy_blade+", 3), 14 + 3 * 5, "the + version is ×5");
    }

    /// §238：`Feed` 的 "If Fatal" —— **目标死了**才抬上限，而且上限与当前血一起 +N。
    ///
    /// 两侧：打死（+3 上限 +3 血）与没打死（一点不涨）。第一版只测了"打死"，于是
    /// "条件被写成恒真"也全绿 —— 那正是 §4 里"守卫装在了切口下游"的形状。
    #[test]
    fn feed_only_raises_max_hp_on_a_fatal_blow() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打死：敌人 5 血，Feed 打 10 ⇒ Fatal ⇒ 上限 70 → 73、当前血 70 → 73（满血时一起涨）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 5;
            enemy.health_current = 5;
        }
        let card = card_in_hand(&mut state, &content, "hero", "feed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("feed is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 0, "the target died");
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.health_max),
            Some(73),
            "Fatal ⇒ Max HP +3"
        );
        assert_eq!(health(&state, "hero"), 73, "and the current HP follows the ceiling");

        // ② 没打死：敌人 100 血 ⇒ 上限一点不动。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "feed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("feed is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 90, "10 damage landed");
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.health_max),
            Some(70),
            "not Fatal ⇒ no Max HP"
        );
    }

    /// §238：`Double Tap` 只认**下一张 Attack**（Duplication Potion 认任意牌）。
    ///
    /// 三件事一起钉住：① Attack 真的打两次；② 那次机会被花掉（第二张 Attack 只打一次）；
    /// ③ **Skill 不吃它**（这是 Double Tap 与 Duplication Potion 唯一的区别，也正是
    /// `DUPLICATION_SCOPES` 里那个 `Some("attack")` 存在的理由 —— 没有它，这张牌会变成"下一张牌"）。
    #[test]
    fn double_tap_only_covers_the_next_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① Attack 打两次：Strike 6 ⇒ 12。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        give(&mut state, "hero", status("st_dt", "standard.double_tap", 1));
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(200 - health(&state, "enemy_a"), 12, "6 damage twice");
        assert_eq!(
            stacks_of(&state, "hero", "standard.double_tap"),
            0,
            "the charge is spent"
        );

        // ② 第二张 Attack 只打一次（机会已经用掉）。
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(200 - health(&state, "enemy_a"), 18, "12 + one more Strike");

        // ③ Skill 不吃 Double Tap：Defend 只给 5 格挡，且那层不被花掉。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        give(&mut state, "hero", status("st_dt", "standard.double_tap", 1));
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 5, "a Skill is played once");
        assert_eq!(
            stacks_of(&state, "hero", "standard.double_tap"),
            1,
            "and a Skill does not spend the charge -- that is the whole difference from the potion"
        );
    }

    /// §238：`Exhume` —— 从**消耗堆**拿一张回手牌（`ChoiceSource::ExhaustPile`）。
    ///
    /// 判据落在"牌真的换了堆"上，而不是"问句出现了"：问句存在只说明内容写了 `chooseCards`，
    /// 挪没挪是内核的事（§161.5 的老教训）。
    #[test]
    fn exhume_pulls_a_card_out_of_the_exhaust_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        // 消耗堆里放一张 `bash`（不用它自己的 exhaustion 造，免得把判据绑在别的牌上）。
        give_card(&mut state, "hero", CardZone::ExhaustPile, "card_ex", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "exhume");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("exhume is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("Exhume asks");
        assert_eq!(
            choice.source.zone(),
            Some(CardZone::ExhaustPile),
            "the question's source zone is the Exhaust pile"
        );
        // 选出答案（消耗堆里那唯一一张），再排空。
        state
            .resolve_choice(crate::state::ChoiceAnswer::Zone(&[0]), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .any(|id| id.as_str() == "bash"),
            "the chosen card is in hand"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "and only Exhume itself is left in the Exhaust pile"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'heavy_blade_multiplies_strength' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 4 tests')


main()
