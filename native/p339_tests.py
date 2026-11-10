"""§339 判据：重写 §331 那两个**固化了错假设**的测试。

## 为什么必须重写，而不是"补一条"

`event_level_requirements_filter_the_pool_before_the_roll` 里：

* `assert!(!pool_has(&above_half, "the_moai_head"), ...)` —— 漏掉"持有 Golden Idol"那一半，
  于是**满血 + 有 Idol 应该出现**被判成"必须不出现"；
* `assert!(!pool_has(&base, "tomb_of_lord_red_mask"), ...)` —— 把"没有面具就遇不到"写成了规范，
  而 wiki 里那正是**获得**面具的途径。

两条都不是"漏测"，是**把错的行为写成了期望值**（与 §338 的折扣公式同一个形状）。

## 覆盖到的组合

| 形状 | 真实内容 | 判据 |
|---|---|---|
| 只有 OR 组（`RequiresAny`） | `the_moai_head` | 2×2 表，四格全测 |
| 只有 AND 组（`Requires`，含 `lacks`） | tomb 的 `Offer all Gold` | 有/无面具 × 金币 |
| 两组都没有 | `winding_halls` | 无条件事件仍在池里 |
| **AND ∧ OR 同时存在** | 内容里今天没有 | 由**两条负控**覆盖：把 OR 组改坏 ⇒ Moai 第 4 格红；把 AND 组改坏 ⇒ tomb 的 offer 红 |

最后一行是**诚实**的：内容里没有"既有 AND 又有 OR"的条目，所以不编一个假条目来测它；
两组各自被真实内容钉住，而求值顺序（先 AND 后 OR）由负控证明不是摆设。
"""

import io

PATH = 'kernel/rd-core/src/content.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

OLD_HEADER = '''    /// §331：**事件级条件** —— `EventTables` 条目的 `Requires` 在**掷之前**筛池。
    ///
    /// 两条真实用户：`The Moai Head`（HP ≤ 50% 才出现）与 `Tomb of Lord Red Mask`（要有红面具）。
    /// 两侧各一次：条件成立时它在池子里、不成立时它**不在** —— 少了后半句，"条件没接上"
    /// （永远在池子里）也会绿。'''

NEW_HEADER = '''    /// §331 / §339：**事件级条件** —— `EventTables` 条目的 `Requires` / `RequiresAny`
    /// 在**掷之前**筛池。
    ///
    /// 两条真实用户，wiki 的原文决定了它们**不是**同一个形状：
    ///
    /// * `The Moai Head`：*"either has Golden Idol, **or** their HP is at or below 50%"* ——
    ///   组内 **OR**（`RequiresAny`，§339）；
    /// * `Tomb of Lord Red Mask`：**无条件**出现（Act 3 池里的普通一员），互斥发生在**选项**上。
    ///
    /// ⚠️ 这条测试的前身把两件事都写反了：它断言"高于 50% 时 Moai **必须不出现**"（漏掉了
    /// Golden Idol 那一半），又断言"没有红面具时 Tomb **根本不在池子里**"（而那正是**获得**
    /// 面具的途径）。**测试把错的行为写成了规范** —— 与 §338 的折扣公式同一个形状。'''

t = sub(t, OLD_HEADER, NEW_HEADER, 'test header')

OLD_BODY = '''        // ① Moai Head：40/80 = 50% ⇒ 在；41/80 > 50% ⇒ 不在。
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
        );'''

NEW_BODY = '''        // ① Moai Head：2×2 表（wiki 是 "either Golden Idol **or** HP ≤ 50%"）。
        //
        //    |            | 无 Idol | 有 Idol |
        //    | 低血(≤50%) |   在    |   在    |
        //    | 高血(>50%) |  不在   | **在**  |   <- 这一格在 §339 之前永远错
        let idol = ["golden_idol"];
        let at_half = crate::run_expr::RunFacts { health: 40, ..base };
        let above_half = crate::run_expr::RunFacts { health: 41, ..base };
        let at_half_idol = crate::run_expr::RunFacts { relics: &idol, ..at_half };
        let above_half_idol = crate::run_expr::RunFacts { relics: &idol, ..above_half };
        assert!(pool_has(&at_half, "the_moai_head"), "low HP, no Idol: it appears");
        assert!(
            pool_has(&at_half_idol, "the_moai_head"),
            "low HP, holding the Idol: still appears"
        );
        assert!(
            !pool_has(&above_half, "the_moai_head"),
            "full HP and no Idol: the only `no` cell"
        );
        assert!(
            pool_has(&above_half_idol, "the_moai_head"),
            "full HP but holding the Golden Idol: it MUST appear (wiki: either ... or ...)"
        );

        // ② Tomb of Lord Red Mask：**无条件**出现。有面具与否都能遇到 —— 这正是"没有面具的
        //    玩家靠献出全部金币换 Red Mask"这条途径的前提。
        let with_mask = crate::run_expr::RunFacts { relics: &["red_mask"], ..base };
        assert!(
            pool_has(&base, "tomb_of_lord_red_mask"),
            "without the Red Mask the tomb must be reachable (that is how you get the mask)"
        );
        assert!(
            pool_has(&with_mask, "tomb_of_lord_red_mask"),
            "and it stays reachable when you already hold it"
        );

        // ②b §339：互斥发生在**选项**上。有面具 ⇒ `[Don the Red Mask]` 可用、`[Offer all Gold]`
        //     锁上；没面具 ⇒ 反过来。读的是**同一个**镜像，所以"事件能遇到"与"哪个选项能点"
        //     必须同时成立 —— 否则玩家会遇到一个没有按钮的房间。
        let step = content
            .event_step("tomb_of_lord_red_mask")
            .expect("the tomb has a step");
        let available = |facts: &crate::run_expr::RunFacts<'_>, label: &str| -> bool {
            for option in step.options.iter().take(usize::from(step.count)) {
                if option.label == label {
                    return crate::run_expr::option_is_available(&content, option.term, facts)
                        .expect("a well-formed requirement");
                }
            }
            panic!("no option labelled {label:?}");
        };
        let rich = crate::run_expr::RunFacts { gold: 100, ..base };
        let rich_with_mask = crate::run_expr::RunFacts {
            gold: 100,
            relics: &["red_mask"],
            ..base
        };
        assert!(
            available(&rich, "Offer all Gold"),
            "no mask + gold: the offer is how you get the mask"
        );
        assert!(
            !available(&rich_with_mask, "Offer all Gold"),
            "holding the mask: the offer is locked (wiki: `[Locked] Requires: Red Mask`)"
        );
        assert!(
            available(&rich_with_mask, "Don the Red Mask (222 gold)"),
            "holding the mask: this is the option that pays 222"
        );
        assert!(
            !available(&rich, "Don the Red Mask (222 gold)"),
            "no mask: `[Don the Red Mask]` is locked"
        );'''

t = sub(t, OLD_BODY, NEW_BODY, 'test body')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('content.rs: §331 test rewritten (2x2 + option exclusivity)')
