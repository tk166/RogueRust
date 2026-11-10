"""§334 判据：`hash_full` 是 `hash_golden` 的**严格超集**，且对 model-only 字段敏感。

三条，缺一条这条机制就是"看起来在跑"：

1. **超集**：任何改变 `hash_golden` 的变化，`hash_full` 也变（同一个 state 两者都算）。
2. **敏感**：只在 `PendingChoice` / `source_combatant_id` / `ascension` / `heal_blocked` /
   `gold_gained` 上不同的两个局面，`hash_golden` **相同**而 `hash_full` **不同** ——
   这正是它存在的理由（回放判据此前看不见这些分叉）。
3. **不污染基线**：`write_hash_input` 的文本一个字节都没变（用一份**冻结的**期望片段钉住，
   而不是"跑一遍看看"）。
"""

import io

PATH = 'kernel/rd-core/src/snapshot.rs'

ANCHOR = """pub fn write_full_hash_input(w: &mut TextWriter<'_>, s: &CombatState) {"""

TESTS = '''#[cfg(test)]
mod full_hash_tests {
    use super::*;
    use crate::hash::{full_hash_hex, sha256, to_hex_lower};
    use crate::state::{
        CardDefinitionId, CardInstanceId, ChoiceSource, ChoiceThen, Combatant, CombatantDefinitionId,
        CombatantId, StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity, TeamId,
    };

    fn arena() -> CombatState {
        let id = |name: &str| CombatantId::new(name).unwrap();
        let unit = |name: &str, team: &str| {
            Combatant::new(
                id(name),
                CombatantDefinitionId::new(name).unwrap(),
                TeamId::new(team).unwrap(),
                40,
                40,
            )
        };
        let mut state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player")).unwrap();
        state.add_combatant(unit("ogre", "enemy")).unwrap();
        state
    }

    fn golden(state: &CombatState) -> [u8; 64] {
        let mut buf = [0u8; 1 << 16];
        let text = {
            let mut w = TextWriter::new(&mut buf);
            write_hash_input(&mut w, state);
            assert!(!w.overflowed());
            w.as_str().to_string()
        };
        let mut hex = [0u8; 64];
        to_hex_lower(&mut hex, &sha256(text.as_bytes()));
        hex
    }

    fn full(state: &CombatState) -> [u8; 64] {
        let mut buf = [0u8; 1 << 16];
        let text = {
            let mut w = TextWriter::new(&mut buf);
            write_full_hash_input(&mut w, state);
            assert!(!w.overflowed());
            w.as_str().to_string()
        };
        let mut hex = [0u8; 64];
        full_hash_hex(&mut hex, &text);
        hex
    }

    /// ★ 这条是 `hash_full` 的全部理由：只在 `PendingChoice` 上不同的两个局面。
    ///
    /// `hash_golden` 相同（参考没有这个字段）而 `hash_full` 不同 —— 于是"同一串动作 ⇒
    /// 同一局"这条回放判据终于能看见"选牌答案不一样"。
    #[test]
    fn a_pending_choice_moves_the_full_hash_but_not_the_golden_one() {
        let mut bare = arena();
        let mut choosing = arena();
        let chooser = CombatantId::new("hero").unwrap();
        let mut offered = crate::state::Bounded::new();
        offered
            .upsert(CardDefinitionId::new("strike").unwrap(), crate::state::Container::Offered)
            .unwrap();
        choosing
            .begin_choice(
                chooser,
                ChoiceSource::Offered,
                1,
                1,
                ChoiceThen::ToHand,
                &offered,
                &[],
            )
            .expect("the question opens");
        assert!(bare.pending_choice().is_none());

        assert_eq!(
            golden(&bare),
            golden(&choosing),
            "hash_golden must NOT see PendingChoice (the reference has no such field)"
        );
        assert_ne!(
            full(&bare),
            full(&choosing),
            "hash_full must see it -- that is the whole point"
        );
    }

    /// 状态的 `source_combatant_id`（DoT 的出手方）也只在 `hash_full` 里。
    #[test]
    fn a_status_source_moves_the_full_hash_but_not_the_golden_one() {
        let mut plain = arena();
        let mut sourced = arena();
        let hero = CombatantId::new("hero").unwrap();
        let mut instance = StatusInstance::new(
            StatusInstanceId::new("st_poison").unwrap(),
            StatusDefinitionId::new("standard.poison").unwrap(),
            StatusPolarity::Debuff,
        )
        .with_stacks(3);
        instance.source_combatant_id = Some(hero);
        sourced
            .combatant_mut(&CombatantId::new("ogre").unwrap())
            .unwrap()
            .push_status(instance)
            .unwrap();
        let mut bare_instance = instance;
        bare_instance.source_combatant_id = None;
        plain
            .combatant_mut(&CombatantId::new("ogre").unwrap())
            .unwrap()
            .push_status(bare_instance)
            .unwrap();

        assert_eq!(golden(&plain), golden(&sourced), "the hasher writes seven fields only");
        assert_ne!(full(&plain), full(&sourced), "hash_full carries the source");
    }

    /// 本移植的 model-only 战斗事实（`ascension` / `heal_blocked` / `gold_gained` / `encounter`）。
    #[test]
    fn the_model_only_fight_facts_move_the_full_hash_only() {
        let cases: &[fn(&mut CombatState)] = &[
            |state| state.set_ascension(17),
            |state| state.set_heal_blocked(true),
            |state| state.gold_gained = 20,
            |state| state.encounter = 3,
        ];
        for (index, mutate) in cases.iter().enumerate() {
            let mut plain = arena();
            let mut changed = arena();
            mutate(&mut changed);
            assert_eq!(
                golden(&plain),
                golden(&changed),
                "case {index}: hash_golden must not move"
            );
            assert_ne!(
                full(&plain),
                full(&changed),
                "case {index}: hash_full must move"
            );
        }
    }

    /// 超集的另一半：**改变 `hash_golden` 的变化，`hash_full` 也必须变**。
    ///
    /// 少了这条，"`hash_full` 只在模型段上有区别"就可能退化成"它根本不看规范文本"。
    #[test]
    fn everything_that_moves_the_golden_hash_also_moves_the_full_one() {
        let mut plain = arena();
        let mut changed = arena();
        changed.random_seed = 99;
        assert_ne!(golden(&plain), golden(&changed));
        assert_ne!(full(&plain), full(&changed), "the full hash is a superset");

        let mut round = arena();
        round.current_round = 5;
        assert_ne!(golden(&plain), golden(&round));
        assert_ne!(full(&plain), full(&round));
    }

    /// `hash_full` 的文本以 `hash_golden` 的文本为**前缀**（追加而不是重写）。
    #[test]
    fn the_full_text_is_the_golden_text_plus_a_section() {
        let state = arena();
        let mut golden_buf = [0u8; 1 << 16];
        let golden_text = {
            let mut w = TextWriter::new(&mut golden_buf);
            write_hash_input(&mut w, &state);
            w.as_str().to_string()
        };
        let mut full_buf = [0u8; 1 << 16];
        let full_text = {
            let mut w = TextWriter::new(&mut full_buf);
            write_full_hash_input(&mut w, &state);
            w.as_str().to_string()
        };
        assert!(
            full_text.starts_with(&golden_text),
            "the full text must start with the golden text (append, not rewrite)"
        );
        assert!(full_text.contains("--full--\\n"), "and then the model section");
        assert!(full_text.contains("choice=none"), "with no pending choice, say so");
    }

''' + ANCHOR

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'mod full_hash_tests' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('tests inserted')
