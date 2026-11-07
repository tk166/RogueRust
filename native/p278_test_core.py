"""§278：把 rd-core 的事件读取器判据改成分段版（并加上"每一步都可达"）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

OLD = '''        let mut ids = Vec::new();
        for index in 0..content.event_count() {
            let (id, text, choices) = content.event(index).expect("event {index}");
            ids.push(id);
            assert!(!text.is_empty(), "{id} has no body text");
            assert!(!choices[0].label.is_empty(), "{id} choice 0 has no label");
            assert!(!choices[1].label.is_empty(), "{id} choice 1 has no label");'''

NEW = '''        let mut ids = Vec::new();
        // §278：**每一步都必须可达**（否则内容里躺着一段谁也看不见的剧情，而屏幕上一切正常）。
        let mut reached: Vec<&str> = Vec::new();
        for index in 0..content.event_count() {
            let (id, _name, entry) = content.event(index).expect("event {index}");
            ids.push(id);
            let step = content
                .event_step(entry)
                .unwrap_or_else(|| panic!("{id}: entry `{entry}` names no step"));
            assert!(!step.text.is_empty(), "{id} has no body text");
            assert!(
                step.count >= 2,
                "{id}: {} option(s) -- an event needs at least two",
                step.count
            );
            let choices = step.options;
            assert!(!choices[0].label.is_empty(), "{id} choice 0 has no label");
            assert!(!choices[1].label.is_empty(), "{id} choice 1 has no label");
            reached.push(entry);
            for option in step.options() {
                if let Some(next) = option.goes_on() {
                    assert!(
                        content.event_step(next).is_some(),
                        "{id}: option `{}` points at `{next}`, which is not a step",
                        option.label
                    );
                    reached.push(next);
                }
            }'''
assert OLD in io.open(P, encoding='utf-8').read()

OLD2 = '''        // Spot-check the pair this section exists for: **relic + curse**, and the A15 branch is a
        // different list (`port-plan.md` §188).
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|e| e.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, choices) = content.event(index).unwrap();'''
NEW2 = '''        // ★ 没有孤儿段：`EVND` 里每一行都要被某个 `EV.Entry` 或某个 `Next` 指到。
        reached.sort_unstable();
        reached.dedup();
        assert_eq!(
            reached.len() as u32,
            content.event_step_count(),
            "{} step(s) in the image, {} reachable -- an unreachable step is a scene nobody can see",
            content.event_step_count(),
            reached.len()
        );

        // Spot-check the pair this section exists for: **relic + curse**, and the A15 branch is a
        // different list (`port-plan.md` §188).
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|e| e.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, entry) = content.event(index).unwrap();
        let step = content.event_step(entry).expect("golden_idol's first step");
        let choices = step.options;'''
assert OLD2 in io.open(P, encoding='utf-8').read()

OLD3 = '''        let effect_of = |id: &str| -> std::vec::Vec<std::string::String> {
            let index = (0..content.event_count())
                .find(|index| content.event(*index).map(|e| e.0) == Some(id))
                .unwrap_or_else(|| panic!("{id} must be in the image"));
            let (_, _, choices) = content.event(index).expect("event");
            std::vec![
                std::string::String::from(choices[0].effects[0].effect),
                std::string::String::from(choices[1].effects[0].effect),
            ]
        };'''
NEW3 = '''        let effect_of = |id: &str| -> std::vec::Vec<std::string::String> {
            let index = (0..content.event_count())
                .find(|index| content.event(*index).map(|e| e.0) == Some(id))
                .unwrap_or_else(|| panic!("{id} must be in the image"));
            let (_, _, entry) = content.event(index).expect("event");
            let step = content.event_step(entry).expect("first step");
            let choices = step.options;
            std::vec![
                std::string::String::from(choices[0].effects[0].effect),
                std::string::String::from(choices[1].effects[0].effect),
            ]
        };'''


def main():
    s = io.open(P, encoding='utf-8').read()
    for old, new in ((OLD, NEW), (OLD2, NEW2), (OLD3, NEW3)):
        assert s.count(old) == 1, old[:60]
        s = s.replace(old, new)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('event test rewritten for steps')


main()
