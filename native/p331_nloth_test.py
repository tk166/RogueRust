"""§331 Phase 2 判据（rd-wasm）：`N'loth` 的端到端。

三件事，缺一条这条判据就变成"看起来在跑"：

1. **候选是两件不同的、真的持有的遗物**（wiki：从当前持有的遗物里随机挑两件）；
2. **标签被替换成那件遗物的显示名**（`Offer: {0}` → `Offer: Golden Idol`）；
3. **点下去真的失去那一件**（`relic_lose:@0` 解析成候选），并拿到 `N'loth's Gift`。

另外验**事件级条件**在运行层的效果：只有 1 件遗物时这个事件**不在池子里**
（`relic_count at_least 2`）—— 那是 Phase 1 的机制在真实内容上的第一个用户。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'

ANCHOR = """    /// §326：`mark_of_the_bloom` ⇒ 战斗状态里的 `heal_blocked` 为真（没有这件遗物时为假）。"""

TESTS = '''    /// §331：`N'loth` —— 两件**随机候选**、标签替换、点下去真的失去那一件。
    ///
    /// wiki：*"It will only appear if the player has at least 2 Relics. Relic A and Relic B will be
    /// randomly chosen from the player's currently held Relics. [Offer: Relic A] Lose this relic.
    /// Obtain a special relic."*
    #[test]
    fn nloth_offers_two_of_the_held_relics_and_takes_the_one_you_pick() {
        reset(11);
        let held: Vec<&'static str> = {
            let session = run_slot().as_ref().expect("a run");
            session.state.relics().iter().map(|id| id.as_str()).collect()
        };
        assert!(held.len() >= 2, "the starter run holds at least two relics: {held:?}");

        // 直接开事件（跳过 `?` 房的掷骰：那条路已经由 `event_level_requirements...` 钉住）。
        {
            let session = run_slot().as_mut().expect("a run");
            session
                .state
                .begin_event("nloth", "nloth")
                .expect("nloth opens");
        }
        // §331：掷两件候选 —— 与 `rd_run_begin_node` 里那一段同一段逻辑。
        assert!(test_roll_event_relic_offer(2).is_ok(), "the offer rolls");
        let (first, second) = {
            let session = run_slot().as_ref().expect("a run");
            (
                std::string::String::from(session.state.event_relic_offer(0).expect("candidate 0")),
                std::string::String::from(session.state.event_relic_offer(1).expect("candidate 1")),
            )
        };
        assert_ne!(first, second, "the two candidates must differ");
        assert!(held.contains(&first.as_str()), "{first} is one of the held relics");
        assert!(held.contains(&second.as_str()), "{second} is one of the held relics");

        // 标签里的 `{0}` 换成了那件遗物的**显示名**（不是 id）。
        let label0 = text(
            rd_run_event_label_len,
            rd_run_event_label_into,
            0,
        );
        assert!(
            label0.starts_with("Offer: ") && !label0.contains('{'),
            "the placeholder is substituted: {label0:?}"
        );
        assert!(
            !label0.contains(&first) || !first.contains('_'),
            "the label shows a display name, not the raw id: {label0:?}"
        );

        // 点第一个：失去候选 0，拿到 N'loth's Gift。
        assert_eq!(rd_run_choose(0), 0, "{}", run_error_text());
        let after: Vec<&'static str> = {
            let session = run_slot().as_ref().expect("a run");
            session.state.relics().iter().map(|id| id.as_str()).collect()
        };
        assert!(
            !after.contains(&first.as_str()),
            "{first} must be gone (took {after:?})"
        );
        assert!(after.contains(&"nloths_gift"), "N'loth's Gift arrives: {after:?}");
        assert_eq!(
            after.len(),
            held.len(),
            "one relic left, one arrived -- the count is unchanged"
        );
    }

    /// §331：只有 1 件遗物时 `N'loth` **不在池子里**（`relic_count at_least 2`）。
    ///
    /// 这是 Phase 1 的事件级条件在真实内容上的第一个用户 —— 判据直接问池子，
    /// 因为"事件屏上按钮被锁"与"事件根本不出现"是两件事，而 wiki 要的是后者。
    #[test]
    fn nloth_stays_out_of_the_pool_below_two_relics() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let one = rd_core::run_expr::RunFacts {
            gold: 0,
            health: 70,
            health_max: 80,
            ascension: 0,
            relics: &["burning_blood"],
            deck: &["strike"],
            floor: 0,
            deck_tags: &[],
            max_hit_damage: 0,
        };
        let two = rd_core::run_expr::RunFacts {
            relics: &["burning_blood", "ring_of_the_snake"],
            ..one
        };
        let has = |facts: &rd_core::run_expr::RunFacts<'_>| {
            content
                .event_pool_at_with_facts("Events2", 5, 0, Some(facts))
                .expect("the act-2 pool")
                .iter()
                .any(|entry| *entry == "nloth")
        };
        assert!(!has(&one), "with one relic N'loth must not be in the pool");
        assert!(has(&two), "with two relics it is");
    }

    /// §326：`mark_of_the_bloom` ⇒ 战斗状态里的 `heal_blocked` 为真（没有这件遗物时为假）。'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn nloth_offers_two_of_the_held_relics' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('nloth tests inserted')
