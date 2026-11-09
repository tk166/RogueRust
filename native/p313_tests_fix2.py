"""§313（六·修 2）：`choose` 的返回值撞上了 `content` 的生命周期。

`ActionChoice<'a>` 的 `action_id` 借自 content ⇒ 闭包不能返回 `Option<&'static str>`。
改成闭包内**直接判断**（`-> bool`）：判据要的就是"这一回合是不是 Heal"。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

OLD_SIG = '''        let choose = |round: i32| -> Option<&'static str> {'''
NEW_SIG = '''        // 返回 `bool` 而不是 `Option<&str>`：`ActionChoice<'a>` 的 id 借自 content，
        // 闭包没法把它活到外面；判据本来就只问"这一回合是不是 Heal"。
        let is_heal = |round: i32| -> bool {'''

OLD_TAIL = '''            rd_core::intent::select_action(&session.state, &content, at, &cid_in("mystic"), round)
                .expect("intent")
                .map(|choice| choice.action_id)
        };'''
NEW_TAIL = '''            rd_core::intent::select_action(&session.state, &content, at, &cid_in("mystic"), round)
                .expect("intent")
                .map_or(false, |choice| choice.action_id == "mystic.heal")
        };'''

OLD_ASSERTS = '''        // ① 满血：Heal 不在候选里。
        assert_ne!(choose(1), Some("mystic.heal"), "nobody is missing 16 HP yet");'''
NEW_ASSERTS = '''        // ① 满血：Heal 不在候选里。
        assert!(!is_heal(1), "nobody is missing 16 HP yet");'''

OLD_2 = '''        assert_eq!(choose(1), Some("mystic.heal"), "an ally is missing 20 HP");'''
NEW_2 = '''        assert!(is_heal(1), "an ally is missing 20 HP");'''

OLD_3 = '''        assert_ne!(
            choose(1),
            Some("mystic.heal"),
            "Heal is capped at two in a row"
        );'''
NEW_3 = '''        assert!(!is_heal(1), "Heal is capped at two in a row");'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    for old, new in ((OLD_SIG, NEW_SIG), (OLD_TAIL, NEW_TAIL), (OLD_ASSERTS, NEW_ASSERTS),
                     (OLD_2, NEW_2), (OLD_3, NEW_3)):
        assert text.count(old) == 1, old[:60]
        text = text.replace(old, new)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)
    print('lifetime fixed')


main()
