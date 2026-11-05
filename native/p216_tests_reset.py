"""§216 test #3: a precise field test for the three scalars `reset_scalars` used to forget."""
import io

S = 'kernel/rd-core/src/state.rs'
text = io.open(S, encoding='utf-8').read()

anchor = """    /// 重置**之后**再往里塞东西，读到的必须只有新塞的 —— 尾巴上的残留不许漏出来。"""
assert text.count(anchor) == 1

NEW = '''    /// §216（审阅 P1-C）：上一场留下的三个标量必须被 `reset_in_place` 清掉 —— **逐字段**，
    /// 不是"按规范哈希文本相等"。
    ///
    /// 为什么不能复用上面那条：`reset_in_place_matches_new_field_for_field` 比的是
    /// `canonical_text`，而 `vacated_seat` / `gold_carried_away` / `ascension` **都不在
    /// `snapshot.rs` 里**（参考实现没有这三个字段）⇒ 它们脏着也照样"逐字段等价"。名字里的
    /// "field for field" 因此是假的，而且会继续放过下一个新字段。
    ///
    /// 后果不是学术性的：`gold_carried_away` 被 `apply_fight_outcome` 用来 `adjust_gold(-n)`
    /// （`rd-wasm/src/run.rs:3491`），复用一份脏状态下一次结算时会**重复扣**一笔被偷的金币。
    #[test]
    fn reset_in_place_also_clears_the_three_scalars_the_hash_text_cannot_see() {
        let mut state = CombatState::new(CombatId::new("dirty").unwrap(), 7);
        state.vacated_seat = Some(3);
        state.gold_carried_away = 40;
        state.set_ascension(20);

        state.reset_in_place(CombatId::new("clean").unwrap(), 9);

        assert_eq!(state.vacated_seat, None, "no seat is left vacant by the previous fight");
        assert_eq!(state.gold_carried_away, 0, "and no gold walks into the next one");
        assert_eq!(state.ascension(), 0, "the run layer sets the level afterwards");
        // 成对：这三个字段确实进过状态（否则上面三行可能只是在比两份默认值）。
        let mut fresh = CombatState::new(CombatId::new("dirty").unwrap(), 7);
        fresh.vacated_seat = Some(3);
        fresh.gold_carried_away = 40;
        fresh.set_ascension(20);
        assert_eq!(fresh.vacated_seat, Some(3));
        assert_eq!(fresh.gold_carried_away, 40);
        assert_eq!(fresh.ascension(), 20);
    }

'''

text = text.replace(anchor, NEW + anchor)
io.open(S, 'w', encoding='utf-8', newline='\n').write(text)
print('reset test added')
