"""§333 判据：`Energized` / `Draw Card` 在**真实回合机**里"只生效一回合"。

这是这条机制唯一的判据要点 —— 它必须**同时**证明三件事：

1. 生效：下一回合的能量是 `基础 + 层数`、抽牌是 `5 + 层数`；
2. 只生效一次：再下一回合回到基础值；
3. 状态**真的消失**（不是层数留 0 赖在状态栏上）。

只测 ① 的话，"每回合都 +X"（也就是把一次性写成永久）照样绿 —— 而那正是"下一回合"与
"每回合"的全部区别。
"""

import io

PATH = 'kernel/rd-core/src/host.rs'

ANCHOR = """    #[test]
    fn the_two_event_curses_behave_as_their_pages_say() {"""

TESTS = '''    /// §333：`standard.energized` / `standard.draw_card_next_turn` —— **只**下一回合。
    ///
    /// 三条一起验（见文件头的理由）：生效一次、下一回合回到基础、状态真的被摘掉。
    #[test]
    fn the_one_shot_turn_start_statuses_apply_once_and_then_go_away() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 11);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state.add_combatant(unit("enemy_a", "enemy", 40, 40)).expect("enemy");
        // 一副够抽的牌：每回合抽 5，两回合要 10 张以上。
        for index in 0..24 {
            give_card(
                &mut state,
                "hero",
                CardZone::DrawPile,
                &std::format!("c{index}"),
                "strike",
                None,
            );
        }
        for entry in [
            status("st_energized", "standard.energized", 2),
            status("st_draw", "standard.draw_card_next_turn", 3),
        ] {
            give(&mut state, "hero", entry);
        }

        let config = config();
        turn::start_current_turn(&mut state, &config, &mut host).expect("turn 1");
        // ① 生效：能量 = 3 + 2、手牌 = 5 + 3。
        assert_eq!(energy_of(&state, "hero"), config.energy_refill + 2, "Energized 2 pays out once");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 8, "Draw Card 3 draws three extra");
        // ③ 状态真的消失（不是留一条 0 层的）。
        for name in ["standard.energized", "standard.draw_card_next_turn"] {
            assert_eq!(stacks_of(&state, "hero", name), 0, "{name} is spent");
        }

        // ② 下一回合回到基础值：先结束这一回合（把能量花掉，免得"补到"语义掩盖差别）。
        turn::end_current_turn(&mut state, &config, &mut host).expect("end turn 1");
        turn::start_current_turn(&mut state, &config, &mut host).expect("turn 2");
        assert_eq!(
            energy_of(&state, "hero"),
            config.energy_refill,
            "the turn after must be back to the plain refill"
        );
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 5, "and the plain five cards");
    }

    /// §222：两张事件诅咒 —— `doubt` 的”回合末 +1 Weak“是 `LifecyclePrograms[TurnEndInHand]`，'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn the_one_shot_turn_start_statuses_apply_once' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('test inserted')
