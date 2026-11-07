"""§279：核心事件判据改成"走遍每一段"（原来只查入口段，所以 §278 的百分比原子漏了）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

OLD_START = '''            let choices = step.options;
            assert!(!choices[0].label.is_empty(), "{id} choice 0 has no label");
            assert!(!choices[1].label.is_empty(), "{id} choice 1 has no label");
            reached.push(entry);'''

OLD_END = '''                    assert!(inside, "{id}: unknown A15 effect {effect:?}");
                }
            }
        }
        ids.sort_unstable();'''

NEW = '''            let choices = step.options;
            assert!(!choices[0].label.is_empty(), "{id} choice 0 has no label");
            if step.count >= 2 {
                assert!(!choices[1].label.is_empty(), "{id} choice 1 has no label");
            }
            reached.push(entry);
        }
        // ★ §279：**走遍每一段**（沿 `Next` 传递），而不是只查入口段。
        // §278 的百分比原子就住在 `golden_idol.boulder` 上，而那段不是入口 —— 旧写法
        // 一条都没检查过它，测试却一直是绿的。
        let mut walk: std::vec::Vec<&str> = std::vec::Vec::new();
        for index in 0..content.event_count() {
            let (_, _, entry) = content.event(index).expect("event");
            walk.push(entry);
        }
        let entry_set = walk.clone();
        let mut at = 0;
        while at < walk.len() {
            let step = content.event_step(walk[at]).expect("a reachable step");
            assert!(!step.text.is_empty(), "step `{}` has no body text", walk[at]);
            for option in step.options() {
                if let Some(next) = option.goes_on() {
                    let step = content.event_step(next).unwrap_or_else(|| {
                        panic!("step `{}`: option `{}` points at `{next}`", walk[at],
                               option.label)
                    });
                    // 后续段可以只有一个选项（`[Leave]`），但**不能一个都没有** ——
                    // 那样这个屏就是一个没有按钮的房间。
                    assert!(step.count >= 1, "step `{next}` has no option at all");
                    if !walk.contains(&next) {
                        walk.push(next);
                    }
                }
            }
            at += 1;
        }
        // The **shape** of the vocabulary is the run layer's business (`EventEffect::parse`);
        // what is pinned here is that the image carries none of the outside: a parsing rule
        // this test cannot see is a rule the content gate alone would have to defend.
        let bare = [
            "heal",
            "gold",
            "damage",
            "max_hp",
            "nothing",
            "remove_card",
            "upgrade_card",
            "transform_card",
        ];
        // §278/§279：`kind:n` 形式的原子（数字在词里）。列在这里而不是用"有冒号就算"，
        // 因为"有冒号就算"会让一个拼错的 kind 静默通过。
        let prefix = |effect: &str, kind: &str| {
            effect.starts_with(kind) && effect.len() > kind.len()
        };
        let inside = |effect: &str| {
            bare.contains(&effect)
                || prefix(effect, "curse:")
                || prefix(effect, "relic:")
                || prefix(effect, "relic_lose:")
                || prefix(effect, "damage_pct:")
                || prefix(effect, "max_hp_pct:")
        };
        for node in &walk {
            let step = content.event_step(*node).expect("step");
            for choice in step.options() {
                // §188：一个选项是一张列表，所以**每一条**都要在闭词表里。
                for spec in &choice.effects[..usize::from(choice.count)] {
                    assert!(
                        inside(spec.effect),
                        "{node}: unknown effect {:?}",
                        spec.effect
                    );
                }
                for spec in &choice.asc[..usize::from(choice.asc_count)] {
                    assert!(
                        inside(spec.effect),
                        "{node}: unknown A15 effect {:?}",
                        spec.effect
                    );
                }
            }
        }
        ids.sort_unstable();'''

def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END, start) + len(OLD_END)
    s = s[:start] + NEW + s[end:]
    # 入口段的 ≥2 判据仍在上面（不动）
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('core event test now walks every step')


main()
