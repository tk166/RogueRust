"""§220 fix: rewrite the sentinel test body (probes out, energy head-room in)."""
import io

P = 'kernel/rd-core/src/host.rs'
text = io.open(P, encoding='utf-8').read()

start = text.index("""            let mut host = Host::new(&content);
            let mut state = arena();
            give_card(&mut state, "hero", CardZone::Hand, "card_sentinel", card_id, None);""")
end = text.index("""            assert_eq!(
                energy_of(&state, "hero"),
                before + expected,
                "{card_id}: wiki says +{expected} Energy when exhausted"
            );""")
end = text.index("        }\n    }\n", end)

new = """            let mut host = Host::new(&content);
            let mut state = arena();
            give_card(&mut state, "hero", CardZone::Hand, "card_sentinel", card_id, None);
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            // 回合开始会把能量补到上限（3/3）—— `gain 2` 会被上限吃掉，所以先把这一格腾出来。
            // 不腾的话"给了 2 点"与"一点没给"在数值上完全一样（第一版就是这么写错的）。
            give_energy(&mut state, "hero", 0);
            let before = energy_of(&state, "hero");
            // 回合末：`ethereal` 把它送进消耗堆 ⇒ `move_card` 发 `Exhausted` ⇒ 节目给能量。
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            // 入队不是执行，排空一次（`end_current_turn` 自己也排，这一步幂等）。
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                zone_count(&state, "hero", CardZone::ExhaustPile),
                1,
                "{card_id}: ethereal moves it to the exhaust pile at turn end"
            );
            assert_eq!(
                energy_of(&state, "hero"),
                before + expected,
                "{card_id}: wiki says +{expected} Energy when exhausted"
            );
        }
    }
"""
text = text[:start] + new + text[end + len("        }\n    }\n"):]
io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('sentinel test rewritten')
