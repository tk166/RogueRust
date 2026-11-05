"""§216 tests #1: `Slow` is now checked **across turns**, and the "wrong pipeline" case is loud."""
import io

H = 'kernel/rd-core/src/host.rs'
M = 'kernel/rd-core/src/modifiers.rs'
X = 'kernel/rd-core/src/exec.rs'


def patch(path, pairs):
    text = io.open(path, encoding='utf-8').read()
    for old, new, what in pairs:
        assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
        text = text.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    print('patched', path)


# ── host.rs：把 §198 那条"层数"测试换成"本回合牌数 + 跨回合" ──────────────────────────────
OLD_SLOW_START = '''    /// §198：`Slow` —— 受击伤害 `×(100 + 10×层数)/100`，并且**每打一张牌 +1 层**。'''
OLD_SLOW_END = '''                stacks_of(&state, "hero", "standard.slow"),
                2 + index as i32,
                "each card played adds one stack"
            );
        }
    }
'''

host_text = io.open(H, encoding='utf-8').read()
start = host_text.index(OLD_SLOW_START)
end = host_text.index(OLD_SLOW_END) + len(OLD_SLOW_END)
NEW_SLOW = '''    /// §216（审阅 P1-A）：`Slow` 的因子是**本回合已出的牌数**，不是层数，也不是整场战斗的牌数。
    ///
    /// wiki（`slay-the-spire.fandom.com/wiki/Slow`）：
    /// *"For every card you have played **this turn**, enemy takes 10% more damage from Attacks,
    /// not compounding. **Slow resets at end of turn**; enemy does NOT carry over stacks."*
    ///
    /// §198 把它做成了"每打一张牌 +1 层、永不衰减" ⇒ 第 2 回合再打 5 张就是 10 层（×200%）。
    /// 那版测试只问"给定层数 → 伤害"，**没有一条跨回合断言**，所以三个层数点全绿也掩盖了它。
    ///
    /// 这一条补的正是缺的那半，而且是**真出牌、真结束回合**（不是伪造计数器 ——
    /// `maw.nom_nom` 的 P1-B 就是被伪造计数器的测试放过的）：
    /// ① 开局 0 张 ⇒ 10 点原样（标记状态在敌人身上，但计数为 0）；
    /// ② 本回合真打 5 张 ⇒ 15 点；
    /// ③ 回合真的结束 ⇒ 内核把牌数清零 ⇒ 又回到 10 点。
    #[test]
    fn slow_counts_the_cards_played_this_turn_and_starts_over_each_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        // 标记状态挂在**敌人**身上（它是 debuff，读的是受击一方）。
        give(&mut state, "enemy_a", status("st_slow", "standard.slow", 1));

        // 一次 10 点直伤打在 enemy_a 上，返回实际掉了多少血。
        let hit = |state: &mut CombatState| -> i32 {
            let before = state.combatant(&cid("enemy_a")).expect("enemy_a").health_current;
            let mut ctx = crate::exec::ExecContext::new(
                state,
                Some(cid("hero")),
                Some(cid("enemy_a")),
                None,
                64,
            )
            .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_a"), 10, false).expect("the blow");
            before - ctx.state.combatant(&cid("enemy_a")).expect("enemy_a").health_current
        };

        // ① 0 张牌：开局**不再自带 +10%**（旧内容的 `Stacks=1` 会在这里给 11 点）。
        assert_eq!(state.cards_played_this_turn, 0);
        assert_eq!(hit(&mut state), 10, "no cards played: a 10-point hit lands for 10");

        // ② 真打 5 张（`defend` 是技能，不会顺手把 enemy_a 打死）。
        give_energy(&mut state, "hero", 9);
        for _ in 0..5 {
            let card = card_in_hand(&mut state, &content, "hero", "defend");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("a defend costs 1 and needs no target");
        }
        assert_eq!(state.cards_played_this_turn, 5, "the kernel counted the real plays");
        assert_eq!(hit(&mut state), 15, "5 cards this turn: 10 * (100 + 10*5) / 100");

        // ③ 回合真的结束（不是写 `cards_played_this_turn = 0`）⇒ 计数归零、加成消失。
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(state.cards_played_this_turn, 0, "turn end resets the counter");
        assert_eq!(hit(&mut state), 10, "next turn starts over: back to 10");
    }
'''
host_text = host_text[:start] + NEW_SLOW + host_text[end:]
io.open(H, 'w', encoding='utf-8', newline='\n').write(host_text)
print('patched', H)

# ── modifiers.rs：运算本身的算术（层数不参与） ────────────────────────────────────────────────
patch(M, [
    ('''    #[test]
    fn scale_percent_ignores_stacks_so_duration_only_statuses_still_apply() {''',
     '''    /// §216：`ScalePercentPerCardPlayedThisTurn` 读的是**本回合牌数**，层数完全无关。
    ///
    /// 判据是 `(牌数, 层数)` 的组合：`(0, 5)` 与 `(5, 1)`、`(5, 99)` 一起出现，才能把
    /// "读错了字段"与"读对了字段"分开 —— 只测 `(5, 1)` 的话，把实现写成 `stacks` 也会绿。
    #[test]
    fn scale_percent_per_card_played_reads_the_turn_count_not_the_stacks() {
        for (cards, stacks, expected) in [(0, 5, 10), (5, 1, 15), (5, 99, 15), (10, 1, 20)] {
            let mut candidate = cand(
                150,
                "standard.slow",
                0,
                stacks,
                Operation::ScalePercentPerCardPlayedThisTurn,
                10,
            );
            candidate.cards_played_this_turn = cards;
            let mut list = [candidate];
            let mut ledger = ClaimLedger::new();
            let applied = apply(10, &mut list, POOL, &mut ledger, 1, &[1]);
            assert_eq!(
                applied.amount, expected,
                "{cards} cards / {stacks} stacks: a 10-point hit lands for {expected}"
            );
        }
    }

    #[test]
    fn scale_percent_ignores_stacks_so_duration_only_statuses_still_apply() {''',
     'modifiers test'),
])

# ── exec.rs：把 Slow 挂到"没有牌数"的管线上必须响亮 ──────────────────────────────────────────
patch(X, [
    ('''fn empty_row<'a>() -> Row<'a> {''',
     '''    /// §216：`Slow` 的运算只在**有本回合牌数**的管线（伤害）里有意义。格挡/抽牌/补能那三条
    /// 管线传 [`NO_TURN_CARDS`]（-1）⇒ 见到这条 spec **拒绝**，而不是安静地按恒等算。
    ///
    /// 成对：同一个 spec 给一个真牌数就正常算（1 张牌 ⇒ 11 点），证明拒绝的是"缺这个量"，
    /// 不是"这条运算本身"。
    #[test]
    fn a_slow_spec_on_a_pipeline_without_a_card_count_is_refused() {
        let mut row = empty_row();
        row.status_id = "standard.slow";
        row.operation = Operation::ScalePercentPerCardPlayedThisTurn;
        row.magnitude = 10;
        let statuses = [status("st_slow", "standard.slow", 1)];
        assert_eq!(
            fold(10, &statuses, &row, &cid("hero"), StatusMatch::Bridged, NO_TURN_CARDS),
            Err(ExecError::Modifier),
            "no card count in this pipeline => refuse, do not silently apply identity"
        );
        assert_eq!(
            fold(10, &statuses, &row, &cid("hero"), StatusMatch::Bridged, 1),
            Ok(11),
            "one card played this turn: 10 * 110 / 100"
        );
    }

fn empty_row<'a>() -> Row<'a> {''',
     'exec test'),
])

print('§216 test patch #1 done')
