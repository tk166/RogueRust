"""§326 判据。

`rd-run`（parasite）：
1. `remove_card`（商店/事件删牌）⇒ 上限 -3；
2. **改造**也算（`transform_card` 是"先 remove 再给一张"）；
3. `remove_all:parasite`（按种类全删）⇒ 每张各 -3；
4. 两侧：删一张**别的**牌上限不变。

`rd-core`（NoHeal 战斗内）：
5. `heal_blocked` 为真时，`heal` 节点、药水级的 `Heal` 请求、以及 `dealDamageAndHealByLoss`
   都回 0（同一处 gate）；`heal_blocked` 为假时同样的调用**真的会回血**。

`rd-wasm`（端到端）：
6. 带 `mark_of_the_bloom` 的局开一场战斗 → `rd_env` 里用一张治疗牌（`bloodletting` 不行，
   用 `reaper`/`feed` 太绕）—— 直接调 `heal` 走不到，所以这里验**状态位**：开战后
   `CombatState.heal_blocked` 必须为真（`rd_env` 无此导出时用一场"+回血"牌的效果代替）。
"""

import io

RUNSTATE = 'kernel/rd-run/src/state.rs'
EXEC = 'kernel/rd-core/src/exec.rs'

RUN_ANCHOR = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

RUN_TESTS = '''    /// §326：`parasite` —— "If transformed or removed from your deck, lose 3 Max HP."
    ///
    /// 四条路径一起验：删牌 / 改造 / 按种类全删 / **删别的牌不该掉上限**。
    /// 最后一条是负向对照 —— 少了它，"每删一张都 -3"的实现也会绿。
    #[test]
    fn parasite_costs_max_health_whenever_it_leaves_the_deck() {
        let pool = basic_pool();
        // ① 删牌。
        let mut run = RunState::new(7, 80, 0, &["parasite", "strike", "defend"])
            .expect("a run");
        run.begin_event("old_beggar", "old_beggar").expect("the event");
        run.begin_event("old_beggar", "old_beggar").expect("the event");
        let before = run.health_max();
        run.resolve_event(EventEffect::RemoveCard, None, &pool).expect("remove");
        run.pick_event_card(0, &pool).expect("the parasite");
        assert_eq!(run.health_max(), before - 3, "removing the Parasite costs 3 max HP");

        // ② 改造（remove + 随机给一张）。
        let mut run = RunState::new(7, 80, 0, &["parasite", "strike", "defend"])
            .expect("a run");
        run.begin_event("living_wall", "living_wall").expect("the event");
        let before = run.health_max();
        run.resolve_event(EventEffect::TransformCard, None, &pool).expect("transform");
        run.pick_event_card(0, &pool).expect("the parasite");
        assert_eq!(run.health_max(), before - 3, "transforming it costs the same 3");

        // ③ 按种类全删（两张 parasite ⇒ -6）。
        let mut run = RunState::new(7, 80, 0, &["parasite", "parasite", "strike"])
            .expect("a run");
        run.begin_event("vampires", "vampires").expect("the event");
        let before = run.health_max();
        run.resolve_event(EventEffect::RemoveAllCards, Some("parasite"), &pool)
            .expect("removing every Parasite");
        assert_eq!(run.health_max(), before - 6, "each copy costs 3");

        // ④ 负向对照：删别的牌，上限不变。
        let mut run = RunState::new(7, 80, 0, &["strike", "defend"])
            .expect("a run");
        run.begin_event("old_beggar", "old_beggar").expect("the event");
        let before = run.health_max();
        run.resolve_event(EventEffect::RemoveCard, None, &pool).expect("remove");
        run.pick_event_card(0, &pool).expect("a strike");
        assert_eq!(run.health_max(), before, "removing an ordinary card is free");
    }

    /// §326：上限被 `parasite` 打到 1 就停 —— 不是"打到 0 甚至负数"。
    ///
    /// 负数上限会让**每一条**按上限算的效果都跟着错（`heal_pct`、`permille_of`、页面血条），
    /// 而那些错都不会响。
    #[test]
    fn parasite_never_takes_the_max_health_below_one() {
        let pool = basic_pool();
        let mut run = RunState::new(7, 80, 0, &["parasite", "strike"]).expect("a run");
        // 直接把上限压到 2，再删一次。
        run.health_max = 2;
        run.health = 2;
        run.begin_event("old_beggar", "old_beggar").expect("the event");
        run.resolve_event(EventEffect::RemoveCard, None, &pool).expect("remove");
        run.pick_event_card(0, &pool).expect("the parasite");
        assert_eq!(run.health_max(), 1, "the floor is 1");
        assert_eq!(run.health(), 1, "and the current health follows it down");
    }

'''


def main():
    t = io.open(RUNSTATE, encoding='utf-8').read()
    assert t.count(RUN_ANCHOR) == 1, 'run anchor'
    assert 'fn parasite_costs_max_health_whenever_it_leaves_the_deck' not in t, 'already patched'
    t = t.replace(RUN_ANCHOR, RUN_TESTS + RUN_ANCHOR)
    io.open(RUNSTATE, 'w', encoding='utf-8', newline='\n').write(t)
    print('rd-run parasite tests inserted')


main()
