"""§348 判据：Boss 身份按**实际掷出的遭遇**，不是池子第一条。

## 旧判据为什么抓不到

`the_boss_id_follows_the_act` 只断言"三幕的 id 互不相同"、并写死 act 1 = `slime_boss` ——
而旧实现就是"每幕取池子第一条"，所以它**必然**通过。第十轮 Review 一句话说清了：
同幕不同种子抽到不同 Boss 时它看不出来。

## 新判据的形状

1. **直接测那个函数**（`boss_enemy_id`，同模块可见）：本幕池里的**每一个** Boss 都nameable，
   而池外的遭遇（普通怪、别幕的 Boss）一律 `None` —— 这比"三幕互不相同"强得多；
2. **ABI 三态**：没有局 `-1`、有局但 Boss 还没定 `0`（空串）、不猜。

第 2 条是这次修复的**行为**：站在 Boss 节点上还没开打时，页面得到空串（"还不知道"），
而不是一个三分之二概率错的答案。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(RUN, encoding='utf-8').read()

OLD_TEST_START = '''    /// §345（缺口 G5）：`rd_run_boss_id_*` 按**幕**给不同的 id。'''

# 找到整条旧测试（从注释到函数结束）—— 用它的结尾锚点切
START = t.index(OLD_TEST_START)
END = t.index('''    /// §346：缺口 G3 / G6 / G7 / G12 的五个导出。''')

NEW_TEST = '''    /// §348（第十轮 Review P1-1）：Boss 身份 = **本局实际掷出的那只**，不是池子第一条。
    ///
    /// 旧实现取"本幕 Boss 池的第一条"，而 `pick_encounter` 是**开战时**才掷的
    /// （`RunStream::Combat`）。本内容每幕三个等权 Boss ⇒ 三分之二的局里页面预告了错的 Boss。
    /// 旧判据（"三幕互不相同"）恰好**必然通过**，所以它抓不到。
    ///
    /// 新判据直接测那个函数：本幕池里**每一个** Boss 都 nameable，池外的一律 `None`。
    #[test]
    fn the_boss_id_names_the_actual_boss_not_the_pool_head() {
        let content = content();

        // ① 本幕池里的**每一个** Boss 都要 nameable —— 这正是"取第一条"过不了的一条。
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
        );

        // ③ ABI 三态：没有局 `-1`、有局但还没打 Boss ⇒ `0`（空串，**不猜**）。
        crate::take_session();
        *run_slot() = None;
        assert_eq!(rd_run_boss_id_len(), -1, "no run at all");
        assert_eq!(rd_run_exists(), 0, "…and `rd_run_exists` agrees");

        reset(7);
        assert_eq!(rd_run_exists(), 1, "a run exists");
        assert_eq!(
            rd_run_boss_id_len(),
            0,
            "before the boss fight we do NOT know which of the three it is -- returning the \\
             pool head here is the bug this test exists for"
        );
    }

'''

t = t[:START] + NEW_TEST + t[END:]
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
print('§348: boss identity test rewritten')
