"""§326 wasm 端到端：带 `mark_of_the_bloom` 开一场战斗，战斗内治疗无效。

判据在**可观察层**：用一张"造成伤害并回血"的牌前后比血量。`reaper`（打 4 回 4）如果不在
手牌里就退一步：直接把英雄打伤 → 调 `rd_env_step` 走一张 `feed`？两条都太依赖手牌。

所以这里选**最稳的一条**：`bloodletting`（失 3 血抽 2 张）**不该**被挡（它不是治疗，是自伤），
而治疗侧用 `rd_env` 的 `heal` 能力没有导出 —— 于是这条判据改成**状态位**：
开战之后内核的 `heal_blocked` 必须为真，且**没有**这件遗物时为假。状态位的可观察后果
由 `rd-core` 的 `a_blocked_fight_heals_nothing_on_any_heal_node` 钉住（3 条 heal 节点）。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'

ANCHOR = """    /// §324：`augmenter` —— 三个选项各走一遍（`?` 房上手动开事件）。"""

TESTS = '''    /// §326：`mark_of_the_bloom` ⇒ 战斗状态里的 `heal_blocked` 为真（没有这件遗物时为假）。
    ///
    /// 为什么在**这一层**验这个一位字段：位本身由 `rd-core` 的判据证明"真的挡住 3 条 heal
    /// 节点"，而"它有没有被接进战斗"只有这一层看得见 —— 两半各测一次，中间那根线才不会被
    /// 漏掉（`set_combat_heal_blocked` 没被调用时，`rd-core` 的判据照样绿）。
    #[test]
    fn mark_of_the_bloom_reaches_the_combat_state() {
        // ① 没有遗物：开战后 `heal_blocked` 为假。
        reset(7);
        assert!(take_blessing() == 0, "the blessing");
        let planted = planted_fight();
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        assert!(
            !crate::slot().as_ref().expect("a fight").state.heal_blocked,
            "a plain run may heal (seed {planted})"
        );
        let _ = rd_run_fight_end();

        // ② 带遗物：为真。
        reset(7);
        assert!(take_blessing() == 0, "the blessing");
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("mark_of_the_bloom", &[])
            .expect("mark of the bloom");
        planted_fight();
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        assert!(
            crate::slot().as_ref().expect("a fight").state.heal_blocked,
            "Mark of the Bloom blocks healing inside the fight too"
        );
    }

'''


def main():
    t = io.open(RUN, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn mark_of_the_bloom_reaches_the_combat_state' not in t, 'already patched'
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS + ANCHOR))
    print('wasm heal_blocked test inserted')


main()
