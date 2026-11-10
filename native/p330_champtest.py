"""§330：Champ 判据改成**真的跑程序**。

旧版是这样进入二阶段的：

```rust
set_counter(&mut state, &actor, "champ_phase", 1);
set_counter(&mut state, &actor, "champ_exec", 1);   // 程序从来没写过这个 1
```

—— 判据把程序该做的事替它做了，于是"Execute 从不回写 `champ_exec`"这个 bug 活了很久。
新版：用 `execute_action` 跑**真**的 `anger` / `execute` / 随机招程序，然后每一步都问
"下一个意图是什么"。wiki 的循环是 **Anger → Execute → 随机 → 随机 → Execute → …**。
"""

import io

PATH = 'kernel/rd-core/src/intent.rs'

OLD = '''        // Drop the boss to half health: the *next* intent is Anger, then Execute.
        {
            let boss = state.combatant_mut(&actor).expect("the champ");
            boss.health_current = boss.health_max / 2;
        }
        assert_eq!(pick(&mut state, 6), "the_champ.anger", "phase two opens with Anger");
        // Anger sets the two counters; the fight would run the program, so set them the same way.
        set_counter(&mut state, &actor, "champ_phase", 1);
        set_counter(&mut state, &actor, "champ_exec", 0);
        assert_eq!(pick(&mut state, 7), "the_champ.execute", "then Execute");
        set_counter(&mut state, &actor, "champ_exec", 1);
        // ⚠️ 第 8 回合**还是** Taunt（每 4 回合一次），所以"循环恢复"要看第 9 回合:
        // `(9-1) % 4 = 0` ⇒ Heavy Slash。这一条是负控的旁证 —— 少写一个数就会在 8 上撞 Taunt。
        assert_eq!(pick(&mut state, 8), "the_champ.taunt", "every 4th round, phase two or not");
        assert_eq!(pick(&mut state, 9), "the_champ.heavy_slash", "afterwards the cycle resumes");
    }'''

NEW = '''        // Drop the boss to half health: the *next* intent is Anger, then Execute.
        {
            let boss = state.combatant_mut(&actor).expect("the champ");
            boss.health_current = boss.health_max / 2;
        }
        assert_eq!(pick(&mut state, 6), "the_champ.anger", "phase two opens with Anger");

        // §330: **跑程序**，不手设计数器 —— 手设的那版替程序写好了 `champ_exec`，
        // 于是"Execute 从不回写它 ⇒ 二阶段每回合都 Execute"这个 bug 一直没被发现。
        let run = |state: &mut CombatState, action_id: &str, round: i32| {
            let row = u32::from(
                content
                    .lookup_in(action_id, crate::content::EK_EACTION)
                    .unwrap_or_else(|| panic!("{action_id}"))
                    .index,
            );
            state.current_round = round;
            execute_action(state, &content, &actor, row, Some(cid("hero")))
                .unwrap_or_else(|e| panic!("{action_id}: {e:?}"));
            crate::exec::drain(state, Some(&content), None).expect("drain");
        };

        run(&mut state, "the_champ.anger", 6);
        assert_eq!(pick(&mut state, 7), "the_champ.execute", "the turn after Anger");
        run(&mut state, "the_champ.execute", 7);

        // wiki: "He will then repeat: Random Move / Random Move / Execute".
        let first = pick(&mut state, 9);
        assert_ne!(first, "the_champ.execute", "Execute must not repeat immediately");
        run(&mut state, &first, 9);
        let second = pick(&mut state, 10);
        assert_ne!(second, "the_champ.execute", "the second random move is still random");
        run(&mut state, &second, 10);
        assert_eq!(
            pick(&mut state, 11),
            "the_champ.execute",
            "after two random moves the cycle owes an Execute"
        );
        run(&mut state, "the_champ.execute", 11);
        assert_ne!(
            pick(&mut state, 12),
            "the_champ.execute",
            "and the cycle restarts after it"
        );
    }'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(OLD) == 1, 'anchor'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(OLD, NEW))
print('champ test now drives the real programs')
