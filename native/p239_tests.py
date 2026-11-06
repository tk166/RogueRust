"""§239 判据：`Clash` 的 PlayCondition（两侧 + 与"没有条件"的对照）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §238：`Heavy Blade` —— **力量算 3（升级 5）次**'

TESTS = '''    /// §239：`Clash` —— **手牌全是攻击牌才能打**（`PlayCondition`）。
    ///
    /// 三段，缺一段这条判据就有一半是空的：
    /// ① 手牌里有技能牌 ⇒ **拒**，而且是 `PlayConditionFalse` 这一种拒（不是"费用不够"或"打不出去"）；
    /// ② 手牌全是攻击 ⇒ 打得出去、伤害是 14；
    /// ③ 拒的时候**一个字节都不改**（能量、手牌、敌人的血）—— 出牌校验在 `apply_plan` 之前。
    ///
    /// 这条同时是"`PlayCondition` 那一格真的进了镜像"的判据：镜像里 62/62 行原本都是 `ABSENT16`，
    /// 若 `contentc` 没把 JSON 的 `PlayCondition` 写进 CARD 行，① 会**通过**（永远可打）而 ② 也通过
    /// ⇒ 只有 ① 能发现接线错了。
    #[test]
    fn clash_refuses_unless_every_card_in_hand_is_an_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 手牌 = Clash + Defend（技能）⇒ 拒。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let clash = card_in_hand(&mut state, &content, "hero", "clash");
        card_in_hand(&mut state, &content, "hero", "defend");
        let energy_before = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        let enemy_before = health(&state, "enemy_a");
        let refused = crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        );
        match refused {
            Err(crate::play::PlayError::Refused(crate::play::Refusal::PlayConditionFalse)) => {}
            other => panic!("a Skill in hand must refuse Clash with PlayConditionFalse, got {other:?}"),
        }
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy_after = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy_after, energy_before, "a refused play pays nothing");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), hand_before, "and the hand is intact");
        assert_eq!(health(&state, "enemy_a"), enemy_before, "and nobody took damage");

        // ② 手牌全是攻击（Clash + Strike）⇒ 打得出去，14 伤害。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let clash = card_in_hand(&mut state, &content, "hero", "clash");
        card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        )
        .expect("an all-attack hand lets Clash through");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 14, "Clash deals 14");

        // ③ 只有 Clash 自己一张手牌 —— 它自己是 Attack，所以也算"全是攻击"（边界）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let clash = card_in_hand(&mut state, &content, "hero", "clash+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        )
        .expect("Clash alone is still an all-attack hand");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 18, "clash+ deals 18");
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'clash_refuses_unless' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 1 test')


main()
