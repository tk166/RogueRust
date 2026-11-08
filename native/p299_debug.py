"""临时诊断：只打一张 Power，然后打印英雄身上的计数器（`orange_pellets` 为什么不付）。"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
TEST = r'''
    #[test]
    fn zzz_debug_orange_pellets_counters() {
        use crate::state::ResourceId;

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        state
            .combatant_mut(&cid("hero"))
            .expect("hero")
            .set_resource(ResourceId::new("standard.energy").unwrap(), 20, Some(20))
            .expect("energy");
        give(&mut state, "hero", status("st_op", "standard.orange_pellets", 1));
        for id in ["metallicize", "strike", "defend"] {
            let card = card_in_hand(&mut state, &content, "hero", id);
            let request = crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a")));
            let outcome = crate::play::play_card(&mut state, Some(&content), &request);
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let counters: Vec<String> = state
                .combatant(&cid("hero"))
                .expect("hero")
                .counters()
                .iter()
                .map(|c| std::format!("{}={}", c.key.as_str(), c.value))
                .collect();
            println!("after {id}: {counters:?}");
            let _ = outcome;
        }
        panic!("diagnostic");
    }
'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + TEST + s[cut:]
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s)
    print('debug test appended')


main()
