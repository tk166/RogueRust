"""§387 的连带：两条**旧内容**的测试要按 wiki 的新事实改写。

## 为什么必须改（而不是"让它们继续绿"）

1. `host::the_boss_phase_splits_once_at_low_health` 把阈值写死成 **≤10 血**，而 wiki 是
   **≤50% 最大血**。旧夹具（`arena()` 的 `enemy_b` 是 10/10）在新规则下**永远不触发** ——
   那不是"测试变严了"，是**夹具让被测行为不可达**（§4.25 的老形状）。
2. `intent::a_combinator_rule_switches_the_boss_move` 断言"半血 ⇒ slam"，而那条规则正是
   §387 删掉的（它把分裂挡掉了）。这条测试的**前提**没了。

改法：
* 第 1 条：把 `enemy_b` 摆成 10/20（正好 50% 之上一点），打 3 点 ⇒ 7/20 落到 50% 以下 ⇒ 分裂；
* 第 2 条：改成断言**新事实**（半血**不**改招；分裂由状态驱动），并把"组合条件"的覆盖
  转到真正还在用它的怪身上（`spheric_guardian` 的 `round == 1 ⇒ activate`）。
"""

import io

# ── 1. host 的阈值 ────────────────────────────────────────────────────────
PATH = 'kernel/rd-core/src/host.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''    fn the_boss_phase_splits_once_at_low_health() {
        // Wiki: the Slime Boss's phase *is* its split. Content trigger: on `DamageTaken`, if my HP is
        // <= 10, spawn two slimes and **consume the phase status** so it cannot fire twice
        // (`port-plan.md` §122).'''
NEW = '''    fn the_boss_phase_splits_once_at_low_health() {
        // Wiki (`Slime Boss`): *"When its HP is at or below 50%, it will split into 2 smaller
        // Slimes with its current HP."* Content trigger: on `DamageTaken`, if `current * 100 <=
        // max * 50`, spawn the two slimes and **consume the phase status** so it cannot fire twice
        // (`port-plan.md` §122, §387).
        //
        // ⚠️ 这条测试以前把阈值写死成"≤10 血"，而 `arena()` 的 `enemy_b` 是 10/10 —— 新规则下
        // 它**永远不触发**（10 血的 50% 是 5）。夹具必须让被测行为可达，所以下面把它摆成 10/20。'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''        let mut state = arena();
        give(&mut state, "enemy_b", status("st_phase", "standard.phase_split", 1));
        let before = state.combatants().len();

        // `enemy_b` is on 10 HP: a 3-point hit lands it at 7, which is <= 10.'''
NEW = '''        let mut state = arena();
        give(&mut state, "enemy_b", status("st_phase", "standard.phase_split", 1));
        // 上限抬到 20（当前仍是 10 = 50%），这样"打到 50% 以下"才可达。
        state
            .combatant_mut(&cid("enemy_b"))
            .expect("enemy_b")
            .health_max = 20;
        let before = state.combatants().len();

        // `enemy_b` is on 10/20: a 3-point hit lands it at 7, and 7 * 100 <= 20 * 50.'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('host 测试：阈值改成 50%')

# ── 2. intent 的组合条件测试 ───────────────────────────────────────────────
PATH2 = 'kernel/rd-core/src/intent.rs'
t2 = io.open(PATH2, encoding='utf-8').read()

OLD2 = '''    fn a_combinator_rule_switches_the_boss_move() {'''
NEW2 = '''    fn a_combinator_rule_switches_the_move() {'''
assert t2.count(OLD2) == 1
t2 = t2.replace(OLD2, NEW2)

OLD3 = '''        let at = slot(&content, "enc_slime_boss", 0);
        let owner = cid(record_id(&content, at));

        let mut state = arena(owner.as_str());
        {
            let combatant = state.combatant_mut(&owner).expect("the boss");
            combatant.health_max = 140;
            combatant.health_current = 70; // exactly 50%
        }
        state.current_round = 1;
        let round_one = select_action(&state, &content, at, &owner, 1)
            .expect("select")
            .expect("an action");
        assert_ne!(
            round_one.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "round 1 must not fire the phase rule yet"
        );

        state.current_round = 2;
        let round_two = select_action(&state, &content, at, &owner, 2)
            .expect("select")
            .expect("an action");
        assert_eq!(
            round_two.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "half health from round 2 on => the phase move"
        );

        state.combatant_mut(&owner).expect("the boss").health_current = 140;
        state.current_round = 5;
        let healthy = select_action(&state, &content, at, &owner, 5)
            .expect("select")
            .expect("an action");
        assert_ne!(
            healthy.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "a healthy boss must not slam"
        );
    }'''

NEW3 = '''        // §387：Slime Boss 的"半血改招"规则**已经删掉**了 —— 它的相位是**分裂**
        // （`standard.phase_split` 的 `DamageTaken` 触发器），不是"换一招"。
        // 所以这里断言的是**新事实**：半血也不改招，招还是那条 `(round-1) % 3` 的循环。
        let boss_at = slot(&content, "enc_slime_boss", 0);
        let boss = cid(record_id(&content, boss_at));
        let mut state = arena(boss.as_str());
        {
            let combatant = state.combatant_mut(&boss).expect("the boss");
            combatant.health_max = 140;
            combatant.health_current = 70; // exactly 50%
        }
        let half_health_moves: Vec<String> = (1..=6)
            .map(|round| {
                select_action(&state, &content, boss_at, &boss, round)
                    .expect("select")
                    .expect("an action")
                    .action_id
                    .to_string()
            })
            .collect();
        assert_eq!(
            half_health_moves,
            vec![
                "slime_boss.goop_spray",
                "slime_boss.preparing",
                "slime_boss.slam",
                "slime_boss.goop_spray",
                "slime_boss.preparing",
                "slime_boss.slam",
            ],
            "half health must NOT change the rotation (the split is a status trigger)"
        );

        // 组合条件（`intent.allOf`）的覆盖转到真正还在用它的怪身上：
        // `spheric_guardian` 有一条 `allOf{round == 1}` ⇒ 第 1 轮 `activate`。
        let orb_at = slot(&content, "enc_sentry_and_spheric", 1);
        let orb = cid(record_id(&content, orb_at));
        let orb_state = arena(orb.as_str());
        let first = select_action(&orb_state, &content, orb_at, &orb, 1)
            .expect("select")
            .expect("an action");
        assert_eq!(
            first.action_id.to_string(),
            "spheric_guardian.activate",
            "`intent.allOf` + `intent.round == 1` must pick the opening move"
        );
        let second = select_action(&orb_state, &content, orb_at, &orb, 2)
            .expect("select")
            .expect("an action");
        assert_eq!(
            second.action_id.to_string(),
            "spheric_guardian.debuff_attack",
            "…and the round-2 rule takes over on the next round"
        );
    }'''
assert t2.count(OLD3) == 1
t2 = t2.replace(OLD3, NEW3)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('intent 测试：改成新事实 + 组合条件换靶子')
