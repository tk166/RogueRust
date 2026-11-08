"""§308 修正：`at_campfire` 的 `node = 5` 与 `floor = 0` 本来就不满足"楼层=行号"这条不变量，
所以拿整局的 `check_invariants()` 当附加判据是错的（那是"助手不合法"，不是"我这块不合法"）。

改成两条更准确的判据：
  * 尾槽清空（行为判据）；
  * 新加的不变量**自己**会被触发（直接塞一条尾槽 mark，再问 `check_invariants`）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch('''        assert!(run.marks[run.deck_len as usize].is_none(), "the tail slot was cleared");
        assert_eq!(run.check_invariants(), Ok(()), "and the run is still legal");''',
'''        assert!(run.marks[run.deck_len as usize].is_none(), "the tail slot was cleared");
    }

    /// §308：新不变量**自己**会响 —— 不是"我知道它写了"，而是"塞一条尾槽 mark 进去它必须报错"。
    ///
    /// ⚠️ 不拿 `at_campfire` 那种助手去测这条：它的 `node = 5` + `floor = 0` 本来就违反
    /// "楼层 = 行号"，于是"有错"与"错在我这一块"分不开（第一版就是这么写的，报的是 floor）。
    #[test]
    fn a_mark_beyond_the_deck_is_an_invariant_violation() {
        let mut run = ironclad();
        let tail = run.deck_len as usize;
        run.marks[tail] = RunMark {
            key: RunId::new("standard.ritual_dagger_bonus").expect("an id"),
            value: 5,
        };
        assert!(
            matches!(run.check_invariants(), Err(RunError::Invariant(what)) if what == "a per-copy mark outlived its card".to_owned()),
            "the tail slot must be refused"
        );
    }''')
    print('fixed')


main()
