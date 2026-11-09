"""§316（四）：Shapes 的两条机制判据 —— 自爆、以及往抽牌堆塞 Dazed。

这两条是本轮**新内容**里唯一有"副作用"的两招：
* `exploder.explode`：30 点伤害 **+ 自己死**（`destroyCombatant`）—— 只测伤害会漏掉"它还站着"；
* `repulsor.daze`：往**抽牌堆**（不是弃牌堆）塞 2 张 `dazed` —— 只测张数会漏掉落区。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §316：Exploder 的 `Explode` —— 30 点伤害之后**自己死**（wiki："Deals 30 damage. Dies."）。
    #[test]
    fn the_exploder_hits_for_thirty_and_then_dies() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let id = shapes_session_with(0, "exploder", 0);
        let hero_before = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).expect("hero").health_current
        };
        {
            let session = slot().as_mut().expect("session");
            let row = u32::from(
                content
                    .lookup_in("exploder.explode", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &id,
                row,
                Some(cid_in("hero")),
            )
            .expect("Explode");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        let session = slot().as_ref().expect("session");
        let hero_after = session.state.combatant(&cid_in("hero")).expect("hero").health_current;
        assert_eq!(hero_before - hero_after, 30, "Explode deals 30");
        let alive = session
            .state
            .combatant(&id)
            .is_some_and(|combatant| {
                combatant.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
            });
        assert!(!alive, "and then it dies");
        take_session();
    }

    /// §316：Repulsor 的 `Daze` —— 2 张 `dazed` 进的是**抽牌堆**（不是弃牌堆）。
    #[test]
    fn the_repulsor_puts_two_dazed_into_the_draw_pile() {
        use rd_core::state::CardZone;
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let id = shapes_session_with(0, "repulsor", 0);
        let count = |state: &rd_core::state::CombatState, zone: CardZone| -> usize {
            let owner = state.combatant(&cid_in("hero")).expect("hero").id;
            state.card_zones(&owner).map_or(0, |zones| zones.count(zone))
        };
        let (draw_before, disc_before) = {
            let session = slot().as_ref().expect("session");
            (count(&session.state, CardZone::DrawPile),
             count(&session.state, CardZone::DiscardPile))
        };
        {
            let session = slot().as_mut().expect("session");
            let row = u32::from(
                content
                    .lookup_in("repulsor.daze", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &id,
                row,
                Some(cid_in("hero")),
            )
            .expect("Daze");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        let session = slot().as_ref().expect("session");
        assert_eq!(
            count(&session.state, CardZone::DrawPile) - draw_before,
            2,
            "two Dazed land in the **draw** pile"
        );
        assert_eq!(
            count(&session.state, CardZone::DiscardPile),
            disc_before,
            "not in the discard pile"
        );
        take_session();
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §315：**同一只怪、两个档位** —— Sentry 在 Act 1 精英池与 Act 2 普通池里 HP 表相同。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('shapes tests added')


main()
