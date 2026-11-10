"""§330：Champ 判据最终版 —— 写入侧（程序）与读取侧（规则）各证一半。

为什么拆两半：在**同一个** `CombatState` 里连跑四个动作会被累积状态干扰（实测：
新 arena 里四个随机招都把 `champ_exec` +1，而连续跑时后面的动作不写）。那种干扰与
"二阶段每回合 Execute"这个 bug 无关，混在一条判据里只会让它变成"有时红有时绿"。

* 写入侧：`anger` 写 -1、`execute` 写 0、四个随机招各 +1 —— 每条都在**新 arena** 里跑真程序；
* 读取侧：`champ_exec == 1` 时不许 Execute、`== 2` 时必须 Execute。

原来的 bug（`execute` 从不回写 ⇒ 每回合 Execute）会被**写入侧**抓住：
`execute` 跑完 `champ_exec` 还是 -1 ⇒ 下一条断言就红。
"""

import io

PATH = 'kernel/rd-core/src/intent.rs'

START = """        // Drop the boss to half health: the *next* intent is Anger, then Execute."""
END = """            "and the cycle restarts after it"
        );
    }"""


def find_block(text):
    a = text.index(START)
    b = text.index(END) + len(END)
    return a, b


NEW = '''        // Drop the boss to half health: the *next* intent is Anger, then Execute.
        {
            let boss = state.combatant_mut(&actor).expect("the champ");
            boss.health_current = boss.health_max / 2;
        }
        assert_eq!(pick(&mut state, 6), "the_champ.anger", "phase two opens with Anger");

        // §330 —— **写入侧**：这些计数器必须由**程序**写，不是判据手设的。
        //
        // 旧版在这里手设 `champ_exec`，于是"`the_champ.execute` 从不回写它 ⇒ 二阶段每回合
        // 都 Execute"这个 bug 活了很久（wiki 的循环是 Anger → Execute → 随机 → 随机 → Execute）。
        let row_of = |action_id: &str| {
            u32::from(
                content
                    .lookup_in(action_id, crate::content::EK_EACTION)
                    .unwrap_or_else(|| panic!("{action_id}"))
                    .index,
            )
        };
        let run_fresh = |action_id: &str, before: i32| {
            let mut fresh = arena("the_champ");
            set_counter(&mut fresh, &actor, "champ_exec", before);
            execute_action(&mut fresh, &content, &actor, row_of(action_id), Some(cid("hero")))
                .unwrap_or_else(|e| panic!("{action_id}: {e:?}"));
            crate::exec::drain(&mut fresh, Some(&content), None).expect("drain");
            fresh
                .combatant(&actor)
                .expect("the champ")
                .counters()
                .iter()
                .find(|c| c.key.as_str() == "champ_exec")
                .map_or(0, |c| c.value)
        };

        // Anger 欠一次 Execute；Execute 用掉它并从 0 重新数；四个随机招各 +1。
        assert_eq!(run_fresh("the_champ.anger", 7), -1, "Anger owes an Execute");
        assert_eq!(run_fresh("the_champ.execute", -1), 0, "Execute clears the debt");
        for action_id in [
            "the_champ.heavy_slash",
            "the_champ.face_slap",
            "the_champ.defensive_stance",
            "the_champ.gloat",
        ] {
            assert_eq!(run_fresh(action_id, 1), 2, "{action_id} counts toward the cycle");
        }

        // §330 —— **读取侧**：1 还不该 Execute，2 必须 Execute。
        set_counter(&mut state, &actor, "champ_phase", 1);
        set_counter(&mut state, &actor, "champ_exec", 1);
        assert_ne!(pick(&mut state, 9), "the_champ.execute", "one random move is not enough");
        set_counter(&mut state, &actor, "champ_exec", 2);
        assert_eq!(
            pick(&mut state, 10),
            "the_champ.execute",
            "after two random moves the cycle owes an Execute"
        );
        // 欠账（-1）也必须是 Execute —— 那是 Anger 之后的那一次。
        set_counter(&mut state, &actor, "champ_exec", -1);
        assert_eq!(pick(&mut state, 11), "the_champ.execute", "the owed Execute comes first");
    }'''

t = io.open(PATH, encoding='utf-8').read()
a, b = find_block(t)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t[:a] + NEW + t[b:])
print('champ test rewritten (writer side + reader side)')
