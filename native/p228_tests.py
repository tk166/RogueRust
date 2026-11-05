"""§228 (part 3): 两张牌的端到端判据。

* `Body Slam`：伤害 == 打出那一刻的格挡；格挡 0 ⇒ 0 伤害（"等于你的格挡"两边都要测）。
* `Sword Boomerang`：3 伤 × 3(4) 次，**每一击各自重掷**目标；判据是
  ① 总量 == 3 × 次数；② 每个敌人身上都是 3 的倍数（不是"一次抽签打 N 下"）；
  ③ `random_step` 正好推进"次数"格（一次抽签一格，与洗牌同一条账）；
  ④ 同一个种子/步数重跑一次，结果逐字相同（随机的**账**是确定的）。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'
src = io.open(HOST, encoding='utf-8').read()

anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1

tests = '''    /// §228：`Body Slam` —— "Deal damage equal to your **Block**"。
    ///
    /// 两端都测：格挡 13 ⇒ 敌人掉 13；格挡 0 ⇒ 掉 0（不是"不掉血所以不报错"，而是真的 0 点伤害）。
    /// 中间那一层（`combatantDefensivePool` 这个表达式）如果读错池子（例如读成能量），两条都会红。
    #[test]
    fn body_slam_deals_damage_equal_to_the_block_it_has_when_played() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (block, expected) in [(13i32, 13i32), (0, 0)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give_block(&mut state, "hero", block);
            let card = card_in_hand(&mut state, &content, "hero", "body_slam");
            let health_before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("body slam is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                health_before - health(&state, "enemy_a"),
                expected,
                "block {block}: the damage of a Body Slam is the Block you had"
            );
        }
    }

    /// §228：`Sword Boomerang` —— 3 伤 × 3(4) 次，**每一击各自抽签**。
    ///
    /// 四件事一起钉（任何一条单独坏掉都还能看起来"在打伤害"）：
    /// ① 总伤害 == 3 × 次数；
    /// ② 每个敌人身上的伤害都是 3 的倍数 —— 否则就是"抽一次签、连打 N 下"；
    /// ③ `random_step` **正好**推进"次数"格（一跳一格，与 `shuffle_candidates` 同一本账）；
    /// ④ 同一个种子与步数重跑，结果逐字相同 —— 随机不等于不可重复。
    #[test]
    fn sword_boomerang_rerolls_a_target_for_each_hit() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // `arena()` 有两个敌人（20 / 10 血），把它们的血抬高，免得第九点伤害就打死一个。
        for (card_id, hits) in [("sword_boomerang", 3), ("sword_boomerang+", 4)] {
            let mut seen = std::vec::Vec::new();
            for _ in 0..2 {
                let mut host = Host::new(&content);
                let mut state = arena();
                give_energy(&mut state, "hero", 3);
                for who in ["enemy_a", "enemy_b"] {
                    if let Some(combatant) = state.combatant_mut(&cid(who)) {
                        combatant.health_max = 200;
                        combatant.health_current = 200;
                    }
                }
                let step_before = state.random_step;
                let card = card_in_hand(&mut state, &content, "hero", card_id);
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
                )
                .expect("sword boomerang is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");

                let a = 200 - health(&state, "enemy_a");
                let b = 200 - health(&state, "enemy_b");
                assert_eq!(
                    a + b,
                    3 * hits,
                    "{card_id}: {hits} hits of 3 damage, got a={a} b={b}"
                );
                assert_eq!(a % 3, 0, "{card_id}: enemy_a took {a}, not a whole number of hits");
                assert_eq!(b % 3, 0, "{card_id}: enemy_b took {b}, not a whole number of hits");
                assert_eq!(
                    state.random_step - step_before,
                    hits,
                    "{card_id}: one draw per hit (and no more) -- {hits} hits, {} draws",
                    state.random_step - step_before
                );
                seen.push((a, b));
            }
            assert_eq!(
                seen[0], seen[1],
                "{card_id}: the same seed and step must give the same hits"
            );
        }
    }

''' + anchor

src = src.replace(anchor, tests)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok tests')
