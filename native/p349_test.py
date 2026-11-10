"""§349 判据：A20 双 Boss 的三种时间语义 + 池成员关系。

## 为什么这样测

跑完整的 A20 三幕流程要打 5 场 Boss，代价太大；而**要钉的是那个函数的时间语义**，
所以直接给它三组参数。三行断言正好覆盖第十一轮 Review 说的那个窗口：

| 场景 | 期望 |
|---|---|
| 双 Boss 之间（第一只已倒、第二只没掷、还没通关） | `None`（**不能**报第一只） |
| 第二只正在打 | 就是它 |
| 第二只已倒（通关屏） | 还是它 —— `bosses_fought` 仍是 1，但我们知道 |

第三行是这次最容易写错的地方：把"双 Boss 之间"的判据写成 `bosses_fought == 1` 而不排除
`boss_beaten`，通关屏就会退化成"本幕 Boss 已击败"。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'


def sub(path, old, new, label, count=1):
    t = io.open(path, encoding='utf-8').read()
    n = t.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


OLD = '''        // ① 本幕池里的**每一个** Boss 都要 nameable —— 这正是"取第一条"过不了的一条。
        assert_eq!(
            boss_enemy_id(content, 1, "enc_slime_boss"),
            Some("slime_boss")
        );
        assert_eq!(
            boss_enemy_id(content, 1, "enc_the_guardian"),
            Some("the_guardian")
        );
        assert_eq!(
            boss_enemy_id(content, 1, "enc_hexaghost"),
            Some("hexaghost")
        );
        assert_eq!(boss_enemy_id(content, 2, "enc_the_champ"), Some("the_champ"));
        assert_eq!(
            boss_enemy_id(content, 3, "enc_time_eater"),
            Some("time_eater")
        );
        // 多敌人的 Boss 取第一个（`Awakened One` 带两个 Cultist）。
        assert_eq!(
            boss_enemy_id(content, 3, "enc_awakened_one"),
            Some("awakened_one")
        );

        // ② 池外的一律 `None`：普通遭遇、**别幕**的 Boss、空串。
        assert_eq!(
            boss_enemy_id(content, 1, "enc_cultist"),
            None,
            "a normal encounter is not a boss"
        );
        assert_eq!(
            boss_enemy_id(content, 2, "enc_slime_boss"),
            None,
            "act 1's boss is not act 2's"
        );
        assert_eq!(
            boss_enemy_id(content, 1, ""),
            None,
            "nothing fought yet: we do not know"
        );'''

NEW = '''        // `calm` = "不在战斗中、不是双 Boss 之间、还没通关" —— 也就是最常见的那个时刻。
        let calm = |act: u8, encounter: &'static str| {
            boss_enemy_id(content, act, encounter, false, 0, false)
        };

        // ① 本幕池里的**每一个** Boss 都要 nameable —— 这正是"取第一条"过不了的一条。
        assert_eq!(calm(1, "enc_slime_boss"), Some("slime_boss"));
        assert_eq!(calm(1, "enc_the_guardian"), Some("the_guardian"));
        assert_eq!(calm(1, "enc_hexaghost"), Some("hexaghost"));
        assert_eq!(calm(2, "enc_the_champ"), Some("the_champ"));
        assert_eq!(calm(3, "enc_time_eater"), Some("time_eater"));
        // 多敌人的 Boss 取第一个（`Awakened One` 带两个 Cultist）。
        assert_eq!(calm(3, "enc_awakened_one"), Some("awakened_one"));

        // ② 池外的一律 `None`：普通遭遇、**别幕**的 Boss、空串。
        assert_eq!(
            calm(1, "enc_cultist"),
            None,
            "a normal encounter is not a boss"
        );
        assert_eq!(
            calm(2, "enc_slime_boss"),
            None,
            "act 1's boss is not act 2's"
        );
        assert_eq!(calm(1, ""), None, "nothing fought yet: we do not know");

        // ③ §349（第十一轮 Review P1-1）：A20 第三幕的**双 Boss 窗口**。
        //
        //    `(act, last_encounter, in_fight, bosses_fought, boss_beaten)`
        //
        //    (a) 第一只已倒、第二只**还没掷** ⇒ **未知**。这是这次修复的行为：
        //        `last_encounter` 还是第一只，把它当成"即将挑战的那只"是错的。
        assert_eq!(
            boss_enemy_id(content, 3, "enc_time_eater", false, 1, false),
            None,
            "between the two A20 bosses we do NOT know the next one"
        );
        //    (b) 第二只正在打 ⇒ 就是它。
        assert_eq!(
            boss_enemy_id(content, 3, "enc_awakened_one", true, 1, false),
            Some("awakened_one")
        );
        //    (c) 第二只已倒（通关屏）⇒ **还是它** —— `bosses_fought` 仍是 1，但我们知道它是谁。
        assert_eq!(
            boss_enemy_id(content, 3, "enc_awakened_one", false, 1, true),
            Some("awakened_one"),
            "the victory screen must still name the boss that was just beaten"
        );'''

sub(RUN, OLD, NEW, 'boss identity test + A20')
print('§349: test rewritten with the A20 window')
