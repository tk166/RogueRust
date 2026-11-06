"""§242 判据：`spot_weakness`（意图两侧 + 非空断言）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §242：`Blood for Blood` —— **每失去 1 次生命便宜 1 点**'

TESTS = r'''    /// §242：`Spot Weakness` —— "If the enemy intends to attack, gain 3 Strength."
    ///
    /// 判据不去写死"哪只怪第一回合攻击"（那是内容的事，会随内容漂），而是**问内核同一个函数**
    /// 玩家看到的那个意图（`intent::select_action` 是页面显示意图的纯函数），然后断言：
    /// 牌的行为与它**一致**。两侧都测 —— 一个"打算攻击"的敌人与一个"不打算攻击"的，
    /// 并且断言两者的意图**确实不同**（否则这条判据会因为两者都是攻击而永远绿）。
    #[test]
    fn spot_weakness_follows_the_enemy_intent() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (遭遇行号, 敌人 id) —— 由内容决定，测试只断言"牌与意图一致"。
        let probe = |encounter: u32, enemy: &str| -> (bool, i32) {
            let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
            state
                .add_combatant(unit("hero", "player", 70, 70))
                .unwrap();
            state.add_combatant(unit(enemy, "enemy", 40, 40)).unwrap();
            state.encounter = encounter;
            // 玩家看到的意图（同一函数）。
            let at = crate::intent::locate_enemy(&content, encounter, &cid(enemy))
                .expect("the encounter resolves")
                .expect("the enemy is in that encounter");
            let kind = crate::intent::select_action(&state, &content, at, &cid(enemy), 1)
                .expect("the intent selects")
                .and_then(|choice| choice.intent_kind);
            let attacks = kind == Some(crate::intent::IntentKind::Attack);

            let mut host = Host::new(&content);
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", "spot_weakness");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid(enemy))),
            )
            .expect("spot weakness is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            (attacks, stacks_of(&state, "hero", "standard.strength"))
        };

        // 遭遇 0 = cultist（第一回合是 Incantation），遭遇 1 = jaw worm（第一回合是 Chomp）。
        let (cultist_attacks, cultist_strength) = probe(0, "cultist");
        let (worm_attacks, worm_strength) = probe(1, "jaw_worm");
        assert!(
            cultist_attacks != worm_attacks,
            "this判据 needs one attacker and one non-attacker (cultist={cultist_attacks}, \
             jaw_worm={worm_attacks})"
        );
        assert_eq!(
            cultist_strength,
            if cultist_attacks { 3 } else { 0 },
            "the card must agree with the displayed intent (cultist)"
        );
        assert_eq!(
            worm_strength,
            if worm_attacks { 3 } else { 0 },
            "the card must agree with the displayed intent (jaw worm)"
        );

        // 没有遭遇（`u32::MAX`）⇒ 意图解不出 ⇒ 不拿力量，而且**不报错**。
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state.add_combatant(unit("jaw_worm", "enemy", 40, 40)).unwrap();
        let mut host = Host::new(&content);
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "spot_weakness");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("jaw_worm"))),
        )
        .expect("spot weakness is playable without an encounter");
        host.try_resolve_pending_queues(&mut state).expect("no encounter is not an error");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            0,
            "no encounter ⇒ no intent ⇒ no Strength (and no error)"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'spot_weakness_follows' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 1 test')


main()
