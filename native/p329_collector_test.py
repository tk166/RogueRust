"""§329 判据：Collector 的**两条**分支都要钉住。

wiki 的分支表：
* 0-1 只 Torch Head 活着：Spawn 25% / Fireball 45% / Buff 30%
* 两只都活着：Fireball 70% / Buff 30%（**不会**再 Spawn）

原来的判据只测了后者（因为它只构造"Collector 自己"这一种局面），而且把 `spawn` 当成
"意外招式"直接 panic —— 于是 §329 加的那条规则一落地它就在**正确的位置**红了
（`unexpected move the_collector.spawn`），这正是"判据写在行为上"的用法。
"""

import io

PATH = 'kernel/rd-core/src/intent.rs'

OLD_START = """    /// 3. **weighted**: over many seeds the split is near 70/30 (a broken picker that always takes the
    ///    first option would be "correct" for rule 1 and 2);
    /// 4. **stateful through content**: with `last_move == 2` (a Buff) the only option left is
    ///    Fireball, which is the wiki's "she cannot use Buff twice in a row".
    #[test]
    fn the_collector_draws_by_weight_and_never_buffs_twice_in_a_row() {"""

NEW_START = """    /// 3. **weighted**: over many seeds each branch matches the wiki's table (a broken picker that
    ///    always takes the first option would be "correct" for rule 1 and 2);
    /// 4. **stateful through content**: with `last_move == 2` (a Buff) the only option left is
    ///    Fireball, which is the wiki's "she cannot use Buff twice in a row";
    /// 5. **§329 the two branches**: with 0-1 Torch Heads alive Spawn is on the table (25%), and with
    ///    both alive it is **not** (Fireball 70 / Buff 30).
    #[test]
    fn the_collector_draws_by_weight_and_never_buffs_twice_in_a_row() {"""

OLD_BODY = """            match first.action_id {
                "the_collector.fireball" => fireballs += 1,
                "the_collector.buff" => buffs += 1,
                other => panic!("seed {seed}: unexpected move {other}"),
            }"""
NEW_BODY = """            match first.action_id {
                "the_collector.fireball" => fireballs += 1,
                "the_collector.buff" => buffs += 1,
                // §329: 场上只有她一个 ⇒ wiki 的 "0-1 Torch Heads alive" 那一支，Spawn 可达。
                "the_collector.spawn" => spawns += 1,
                other => panic!("seed {seed}: unexpected move {other}"),
            }"""

OLD_TAIL = """        // 3. weighted: 400 draws of a 70/30 split. The bounds are wide on purpose (±8 points) --
        // this is a *distribution* check, not a bit-exact golden; the point is to catch "always the
        // first option" (buffs would be 0) and "ignores the weights" (50/50).
        let total = fireballs + buffs;
        let ratio = fireballs as f64 / total as f64;
        assert!(
            (0.62..=0.78).contains(&ratio),
            "Fireball took {fireballs}/{total} = {ratio:.2}, wiki says 70%"
        );
        assert!(buffs > 0, "Buff must be reachable");
    }"""

NEW_TAIL = """        // 3. weighted, branch A (0-1 Torch Heads alive): 25/45/30. Bounds are wide on purpose --
        // a distribution check, not a bit-exact golden. The point is to catch "always the first
        // option" and "ignores the weights" (a flat 33/33/33 would fail every one of these).
        let total = fireballs + buffs + spawns;
        let share = |n: usize| n as f64 / total as f64;
        assert!(
            (0.18..=0.32).contains(&share(spawns)),
            "Spawn took {spawns}/{total} = {:.2}, wiki says 25%",
            share(spawns)
        );
        assert!(
            (0.38..=0.52).contains(&share(fireballs)),
            "Fireball took {fireballs}/{total} = {:.2}, wiki says 45%",
            share(fireballs)
        );
        assert!(
            (0.24..=0.37).contains(&share(buffs)),
            "Buff took {buffs}/{total} = {:.2}, wiki says 30%",
            share(buffs)
        );

        // 5. branch B (both Torch Heads alive): Fireball 70 / Buff 30, and **no Spawn at all**.
        let mut heads_fireballs = 0usize;
        let mut heads_buffs = 0usize;
        for seed in 0..400 {
            let mut state = {
                let mut state = arena("the_collector");
                state.random_seed = seed;
                state.current_round = 5;
                for index in 0..2 {
                    state
                        .add_combatant(unit(
                            &std::format!("torch_head_{index}"),
                            "enemy",
                            38,
                        ))
                        .expect("a Torch Head");
                }
                state
            };
            // 两只 Torch Head 都活着 ⇒ 敌人 3 个，wiki 的 "both alive" 那一支。
            let first = select_action(&state, &content, at, &actor, 5)
                .expect("intent")
                .expect("an action");
            match first.action_id {
                "the_collector.fireball" => heads_fireballs += 1,
                "the_collector.buff" => heads_buffs += 1,
                other => panic!("seed {seed}: {other} must be unreachable with two Torch Heads"),
            }
        }
        let total = heads_fireballs + heads_buffs;
        let ratio = heads_fireballs as f64 / total as f64;
        assert!(
            (0.62..=0.78).contains(&ratio),
            "with two Torch Heads Fireball took {heads_fireballs}/{total} = {ratio:.2}, wiki says 70%"
        );
        assert!(heads_buffs > 0, "Buff must be reachable");
    }"""


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()
t = sub(t, OLD_START, NEW_START, 'doc + fn')
t = sub(t, OLD_BODY, NEW_BODY, 'match body')
t = sub(t, """        let mut fireballs = 0usize;
        let mut buffs = 0usize;""",
        """        let mut fireballs = 0usize;
        let mut buffs = 0usize;
        let mut spawns = 0usize;""",
        'counters')
t = sub(t, OLD_TAIL, NEW_TAIL, 'tail')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('collector intent test now pins both branches')
