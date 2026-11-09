"""§312（三·修）：第一版判据把蛇草打死了（50 点 ×3 打 75 血的怪）。

而且"块是累加的"这个预期也是错的：**格挡会被伤害吃掉**，所以每次命中后的读数其实是
"这次给的那一块"（3 / 4 / 5），不是累加值。这两点都是判据写错，不是实现对错 —— 所以这一版：

* 每次 12 点（三下共 36，怪不死）；
* 期望 [3, 4, 5]（每一击给的块 = 层数 + 已触发次数）；
* 回合开始后又是 3；
* 毒用 1 点：先吃掉 1 块（3 → 2），**不**给块 ⇒ 2（若误触发会是 2 + 4）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

OLD_BODY = '''        // 1 + 2: 三下攻击 ⇒ 3 / 7 / 12。
        let mut seen = Vec::new();
        for _ in 0..3 {
            hit(DamageKind::Direct);
            let session = slot().as_ref().expect("session");
            seen.push(block(&session.state));
        }
        assert_eq!(seen, vec![3, 7, 12], "Malleable 3, then +4, then +5 (blocks accumulate)");'''

NEW_BODY = '''        // 1 + 2: 三下攻击（12/12/12）⇒ 每一击**给的**块是 3 / 4 / 5。
        // ⚠️ 读数就是"这次给的那一块"：上一次的块会被这一击吃掉，所以**不是累加值**
        // （第一版在这里写了 [3, 7, 12]，那是把格挡当成了不消耗的）。
        let mut seen = Vec::new();
        for _ in 0..3 {
            hit(DamageKind::Direct);
            let session = slot().as_ref().expect("session");
            seen.push(block(&session.state));
        }
        assert_eq!(seen, vec![3, 4, 5], "Malleable pays 3, then 4, then 5");'''

OLD_RESET = '''        hit(DamageKind::Direct);
        let session = slot().as_ref().expect("session");
        let after_reset = block(&session.state);
        assert_eq!(
            after_reset,
            12 + 3,
            "the counter reset, so the next hit pays the base 3 again (12 already banked)"
        );'''

NEW_RESET = '''        hit(DamageKind::Direct);
        let session = slot().as_ref().expect("session");
        let after_reset = block(&session.state);
        assert_eq!(
            after_reset, 3,
            "the counter reset, so the next hit pays the base 3 again (not 6)"
        );'''

OLD_DOT = '''        // 4: 毒**不**让它长大（`damage.isAttack` 为假）。
        {
            let before = block(&session.state);
            hit(DamageKind::Dot);
            let session = slot().as_ref().expect("session");
            assert_eq!(block(&session.state), before, "DoT is not an attack");
        }'''

NEW_DOT = '''        // 4: 毒**不**让它长大（`damage.isAttack` 为假）。用 1 点毒：先吃掉 1 块（3 → 2），
        // 若它误触发就会变成 2 + 4 = 6 —— 两种读数分得开。
        {
            hit_dot(1);
            let session = slot().as_ref().expect("session");
            assert_eq!(block(&session.state), 2, "DoT eats block but never pays Malleable");
        }'''

OLD_HIT = '''        let hit = |kind: DamageKind| {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("snake_plant")),
                None,
                1024,
            )
            .with_content(&content);
            // 50 点：一定要打穿已有的块，否则 `eventAmount == 0` ⇒ 不触发（见文档）。
            rd_core::exec::resolve_damage_of_kind(&mut ctx, &cid_in("snake_plant"), 50, false, kind)
                .expect("an attack lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch DamageTaken");
        };'''

NEW_HIT = '''        let deal = |kind: DamageKind, amount: i32| {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("snake_plant")),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage_of_kind(
                &mut ctx,
                &cid_in("snake_plant"),
                amount,
                false,
                kind,
            )
            .expect("damage lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch DamageTaken");
        };
        // 12 点：打穿已有的块（每次 3/4/5），但三下不会把 75 血的蛇草打死。
        let hit = |kind: DamageKind| deal(kind, 12);
        let hit_dot = |amount: i32| deal(DamageKind::Dot, amount);'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    for old, new in ((OLD_BODY, NEW_BODY), (OLD_RESET, NEW_RESET), (OLD_DOT, NEW_DOT), (OLD_HIT, NEW_HIT)):
        assert text.count(old) == 1, old[:70]
        text = text.replace(old, new)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)
    print('test fixed')


main()
