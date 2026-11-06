"""§249 判据：Omega / Panache / Sadistic Nature / The Bomb（挂在 `host.rs` 测试模块里）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// 读盘上的 sts 镜像（四条判据共用；每条都从**同一份产物**出发）。
    fn sts_image() -> Content<'static> {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        // `Content` 借的是这块字节，所以必须泄漏成 `'static`：测试进程一次，代价可以忽略。
        parse(Box::leak(blob.into_boxed_slice()))
    }

    /// 把两个敌人的血调高，好让"掉了几点"不被死亡吞掉。
    fn beefy(state: &mut CombatState) {
        for enemy in ["enemy_a", "enemy_b"] {
            if let Some(combatant) = state.combatant_mut(&cid(enemy)) {
                combatant.health_max = 500;
                combatant.health_current = 500;
            }
        }
    }

    /// §249：`Omega` —— `TurnEnded` 触发器按**自己的层数**打全体。
    ///
    /// 判据两侧：未到回合末不掉血（防"触发器被当成 `TurnStarted`"），回合末两个敌人都掉 50
    /// （防"只打第一个"/"只打一次"）。
    #[test]
    fn omega_hits_every_enemy_at_the_end_of_the_turn() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        give(&mut state, "hero", status("st_om", "standard.omega", 50));
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        assert_eq!(health(&state, "enemy_a"), 500, "开场不掉血");
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 450);
        assert_eq!(health(&state, "enemy_b"), 450, "**每一个**敌人");
    }

    /// §249：`Panache` —— 每回合第 5/10/15… 张牌打出时各打一次全体。
    ///
    /// 载体是 `cardsPlayedThisTurn` + `remainder`（§249 才把这四条算术实现掉）。
    /// 判据三点：第 4 张不响、第 5 张响（10 点 × 2 个敌人 = 20）、第 6 张不再响。
    /// 出的是 `flex`（0 费、只给自己加力量）—— 选它是因为它**不动敌人**，
    /// 所以敌人掉的每一点血都只能来自 Panache。
    #[test]
    fn panache_fires_on_every_fifth_card_of_the_turn() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        give(&mut state, "hero", status("st_pan", "standard.panache", 10));
        state
            .combatant_mut(&cid("hero"))
            .expect("hero")
            .set_resource(
                crate::state::ResourceId::new("standard.energy").expect("energy"),
                99,
                Some(99),
            )
            .expect("cap");
        let missing = |state: &CombatState| -> i32 {
            (500 - health(state, "enemy_a")) + (500 - health(state, "enemy_b"))
        };
        let mut per_card = Vec::new();
        for index in 1..=6 {
            give_card(&mut state, "hero", CardZone::Hand,
                      &std::format!("card_f{index}"), "flex", None);
            let card = crate::state::CardInstanceId::new(&std::format!("card_f{index}"))
                .expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("flex is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            per_card.push(missing(&state));
        }
        assert_eq!(
            per_card,
            [0, 0, 0, 0, 20, 20],
            "第 4 张之前不动、第 5 张打 10×2、第 6 张不再打"
        );
    }

    /// §249：`Sadistic Nature` —— 只有"**debuff** 落在**别人**身上"才触发。
    ///
    /// 三段把两个事实位各测两侧（§249 的两个新 flag）：
    /// ① 给敌人挂 `weak`（debuff + 落在别人）⇒ 掉 5；
    /// ② 给自己挂 `weak`（debuff 但 `appliedToOther` 假）⇒ 不掉；
    /// ③ 给敌人挂 `strength`（落在别人但 `isDebuff` 假）⇒ 不掉。
    /// 缺任何一段，一个"永远触发"或"永不触发"的实现都能蒙过。
    #[test]
    fn sadistic_nature_needs_a_debuff_on_someone_else() {
        let content = sts_image();
        let hits = |target: &str, definition: &str| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            beefy(&mut state);
            // 玩家挂 `strength`，让"给自己挂 buff"那一段也有血可看。
            give(&mut state, "hero", status("st_sn", "standard.sadistic_nature", 5));
            let request = crate::state::EffectRequest::ApplyStatus {
                target: Some(cid(target)),
                definition: crate::state::StatusDefinitionId::new(definition).expect("id"),
                stacks: 1,
                duration: 0,
                charges: 0,
                source: Some(cid("hero")),
                source_card: None,
            };
            let item = crate::state::EffectItem {
                request,
                chain: crate::state::ChainSlot::NONE,
                owner: None,
            };
            crate::exec::resolve_effect(&mut state, &item, Some(&content))
                .expect("the status lands");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            500 - health(&state, target)
        };
        assert_eq!(hits("enemy_a", "standard.weak"), 5, "debuff 落在敌人身上 ⇒ 5");
        assert_eq!(hits("hero", "standard.weak"), 0, "debuff 落在**自己**身上 ⇒ 不响");
        assert_eq!(hits("enemy_a", "standard.strength"), 0, "buff 落在敌人身上 ⇒ 不响");
    }

    /// §249：`The Bomb` —— 第 **3** 个回合末炸一次，之后再炸不出来。
    ///
    /// 顺序是语义：先判"这是最后一层吗"再自减。反过来写就变成"第 4 回合才炸"，
    /// 而那在页面上看起来完全正常（只是晚了一回合），所以判据给的是**每回合掉血序列**
    /// `[0, 0, 40, 40]`（第 4 段必须是 40 —— 它证明"只炸一次"）。
    #[test]
    fn the_bomb_explodes_on_the_third_turn_end_only() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        give(&mut state, "hero", status("st_bd", "standard.the_bomb_damage", 40));
        give(&mut state, "hero", status("st_b", "standard.the_bomb", 3));
        let mut per_turn = Vec::new();
        for _ in 0..4 {
            turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
            turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            per_turn.push(500 - health(&state, "enemy_a"));
        }
        assert_eq!(
            per_turn,
            [0, 0, 40, 40],
            "第 3 个回合末炸 40，第 4 个回合末不再炸"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'panache_fires_on_every_fifth_card_of_the_turn' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 4 tests')


main()
