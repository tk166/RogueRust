"""§326 判据（rd-core）：`heal_blocked` 挡住战斗内的**每一条**治疗路径。

镜像里 `node.heal` 有 3 条，全部走同一个 `heal_for`；这里对**每一条**都验两侧：
置位时回 0、不置位时真的回血。只验一条会漏掉"某条节点绕过了汇"的实现。
"""

import io

EXEC = 'kernel/rd-core/src/exec.rs'

ANCHOR = """    #[test]
    fn heal_heals_up_to_max_but_never_past_it() {"""

TESTS = '''    /// §326：`mark_of_the_bloom` —— 战斗内**一律**不回血（`heal_for` 是唯一汇）。
    ///
    /// 两侧：置位时 3 条 `node.heal` 都回 0；**不置位**时它们真的回血 —— 少了后半句，
    /// "把 heal 全禁了"的实现也会绿。
    #[test]
    fn a_blocked_fight_heals_nothing_on_any_heal_node() {
        let blob = core_image();
        let content = parse(&blob);
        let heals = terms_of_kind(&content, "node.heal");
        assert!(!heals.is_empty(), "镜像里要真的有 heal 节点");

        for tid in heals {
            let node = NodeRef::new(&content, tid);

            // ① 不挡：会回血（先记下回了多少）。
            let mut open_state = arena();
            open_state.combatant_mut(&cid("hero")).unwrap().health_current = 10;
            run_program(&mut open_state, node, Some("hero"), None, 1024).unwrap();
            let healed = open_state.combatant(&cid("hero")).unwrap().health_current;
            assert!(healed > 10, "an unblocked heal must actually heal (node {tid})");

            // ② 挡：血量一点不动。
            let mut blocked = arena();
            blocked.set_heal_blocked(true);
            blocked.combatant_mut(&cid("hero")).unwrap().health_current = 10;
            run_program(&mut blocked, node, Some("hero"), None, 1024).unwrap();
            assert_eq!(
                blocked.combatant(&cid("hero")).unwrap().health_current,
                10,
                "a blocked heal leaves the health alone (node {tid})"
            );
        }
    }

    #[test]
    fn heal_heals_up_to_max_but_never_past_it() {'''


def main():
    t = io.open(EXEC, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn a_blocked_fight_heals_nothing_on_any_heal_node' not in t, 'already patched'
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
    print('rd-core blocked-heal test inserted')


main()
