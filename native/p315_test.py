"""§315（三）：判据 —— `(monster, tier)` 的 HP 建模真的成立。

要证明的**不是**"这条遭遇能建起来"（`every_encounter...` 已经管了），而是：
1. 同一只 Sentry 在**精英**遭遇与**普通**遭遇里带的是**同一条** `MaxHealthAsc`（`{A8, 39}`）
   —— 这正是"档位按怪物自己钉"的意思；
2. **A7 时它是 38、A8 时是 39**（Act 2 的普通遭遇里也一样）—— 只钉 A8 不会把 A7 提前改掉，
   因为内核取"≤ ascension 的最大阈值"，而 A7 时没有行可用；
3. 同一条遭遇的第二个槽位（Spheric Guardian）的开局 40 块仍然生效 —— 换槽位/换池子不该
   把已有的 `StartingBlock` 弄丢。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §315：**同一只怪、两个档位** —— Sentry 在 Act 1 精英池与 Act 2 普通池里 HP 表相同。
    ///
    /// 这条判据钉的是"建模"而不是"这一条遭遇"：
    /// * 两处记录里的 `MaxHealthAsc` 必须**一字不差**（否则就是两套数字，迟早漂）；
    /// * A7 时 38、A8 时 39 —— 只钉 A8 不会在 A7 提前生效（内核取"≤ ascension 的最大阈值"）。
    #[test]
    fn the_sentry_keeps_one_hp_table_across_two_tiers() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        // 两个遭遇里的 Sentry 记录：`MaxHealthAsc` 必须相同（内容层面）。
        let rows: Vec<Vec<i32>> = ["enc_three_sentries", "enc_sentry_and_spheric"]
            .iter()
            .map(|eid| {
                let index = u32::from(
                    content
                        .lookup_in(eid, rd_core::content::EK_ENCOUNTER)
                        .unwrap_or_else(|e| panic!("{eid}: {e:?}"))
                        .index,
                );
                let enemies = content.encounter_enemies(index).expect("enemies");
                let spec = enemies
                    .iter()
                    .next()
                    .expect("one enemy")
                    .expect("the record");
                let base = spec.max_health().expect("MaxHealth").expect("a number");
                let pinned = spec
                    .max_health_asc(8)
                    .expect("MaxHealthAsc")
                    .expect("an A8 row");
                vec![base, pinned]
            })
            .collect();
        assert_eq!(rows[0], rows[1], "the same monster carries the same table in both pools");
        assert_eq!(rows[0], vec![38, 39], "wiki: 38-42, A8+ 39-45");

        // 实战：A7 仍是 38，A8 才是 39（在**普通**遭遇里也一样）。
        for (ascension, expected) in [(7u8, 38i32), (8u8, 39i32)] {
            let session = build_session_at(41, "enc_sentry_and_spheric", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let session = slot().as_ref().expect("session");
            let sentry = session
                .state
                .combatant(&cid_in("sentry_1"))
                .expect("the sentry is here");
            assert_eq!(
                sentry.health_max, expected,
                "A{ascension}: the wiki's HP table, not the pool's tier"
            );
            // 第二个槽位的开局块没丢（`StartingBlock` 与 HP 表是两件事）。
            let guardian_block = session
                .state
                .combatant(&cid_in("spheric_guardian"))
                .expect("the guardian is here")
                .defensive_pools()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.block")
                .map_or(0, |pool| pool.pool.current);
            assert_eq!(guardian_block, 40, "A{ascension}: the guardian still starts with 40 Block");
            take_session();
        }
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §314：Mugger —— 和 Looter **同一套出招**（wiki 原话），数字是 Act 2 的。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('sentry tier test added')


main()
