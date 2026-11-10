"""§331 判据（内容侧）：事件级条件真的在**池子**上生效。

两侧都测：Moai 的 `health_percent at_most 50`、Tomb 的 `relic has red_mask` —— 每一条都在
"成立 / 不成立"两种事实下各取一次池子，然后断言"在 / 不在"。

⚠️ 只测"成立时在池子里"是不够的：那对"条件完全没接上"的实现也是绿的（它永远在）。
"""

import io

PATH = 'kernel/rd-core/src/content.rs'

ANCHOR = """        // The roguedeck image has **no** `UnknownRooms` key, so it has no events -- not an error."""

TESTS = '''    /// §331：**事件级条件** —— `EventTables` 条目的 `Requires` 在**掷之前**筛池。
    ///
    /// 两条真实用户：`The Moai Head`（HP ≤ 50% 才出现）与 `Tomb of Lord Red Mask`（要有红面具）。
    /// 两侧各一次：条件成立时它在池子里、不成立时它**不在** —— 少了后半句，"条件没接上"
    /// （永远在池子里）也会绿。
    #[test]
    fn event_level_requirements_filter_the_pool_before_the_roll() {
        let blob = std::fs::read(IMAGE).expect("the sts image");
        let content = Content::parse(&blob).expect("parses");
        let base = crate::run_expr::RunFacts {
            gold: 0,
            health: 40,
            health_max: 80,
            ascension: 0,
            relics: &[],
            deck: &["strike"],
            floor: 0,
            deck_tags: &[],
            max_hit_damage: 0,
        };
        let pool_has = |facts: &crate::run_expr::RunFacts<'_>, id: &str| {
            let pool = content
                .event_pool_at_with_facts("Events3", 12, 0, Some(facts))
                .expect("the act-3 pool");
            pool.iter().any(|entry| !entry.is_empty() && *entry == id)
        };

        // ① Moai Head：40/80 = 50% ⇒ 在；41/80 > 50% ⇒ 不在。
        let at_half = crate::run_expr::RunFacts { health: 40, ..base };
        let above_half = crate::run_expr::RunFacts { health: 41, ..base };
        assert!(pool_has(&at_half, "the_moai_head"), "at 50% the Moai Head can appear");
        assert!(
            !pool_has(&above_half, "the_moai_head"),
            "above 50% the Moai Head must not appear (wiki: only below half HP)"
        );

        // ② Tomb of Lord Red Mask：有红面具 ⇒ 在；没有 ⇒ 不在。
        let with_mask = crate::run_expr::RunFacts { relics: &["red_mask"], ..base };
        assert!(pool_has(&with_mask, "tomb_of_lord_red_mask"), "holding the mask opens the tomb");
        assert!(
            !pool_has(&base, "tomb_of_lord_red_mask"),
            "without the Red Mask the tomb is not in the pool at all"
        );

        // ③ 没有 `Requires` 的事件不受影响（否则"全池都被筛掉"也会让上面两条绿）。
        assert!(pool_has(&base, "winding_halls"), "an unconditional event stays in the pool");

        // ④ `event_pool_at`（不带 facts）**不筛** —— 存量调用与测试的语义没变。
        let unfiltered = content.event_pool_at("Events3", 12, 0).expect("the act-3 pool");
        assert!(
            unfiltered.iter().any(|entry| *entry == "tomb_of_lord_red_mask"),
            "without facts nothing is filtered out"
        );
    }

        // The roguedeck image has **no** `UnknownRooms` key, so it has no events -- not an error.'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn event_level_requirements_filter_the_pool_before_the_roll' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('content test inserted')
