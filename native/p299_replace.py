"""§299：整条替换 `dead_branch` 判据（按函数边界定位，不按行号）。

到这一步文件已经被几次补丁搞花了：`dead_branch` 判据尾部残留了旧 assert 的两行。
所以这里按 **`fn dead_branch_adds…` 到下一个 `fn `** 的边界整段替换成一份干净版本。
"""
import io

HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'

CLEAN = r'''    /// §299：`dead_branch` —— 每**消耗**一张牌，往手牌加一张随机牌。
    ///
    /// ① 带状态时手牌 +1；② 不带时不动；③ 新牌是**基础牌**（不是 `+` 行、不是 X 费牌 ——
    /// 那两条是随机池的规矩，通配 tag `*` **不**越过它们）；
    /// ④ 池子是**任意牌**：在同一场战斗里连抽，三种卡的种类都必须出现。
    ///
    /// ⚠️ ④ 必须在**同一场战斗里**连抽：每次新建 `arena()` 拿到的是同一个 seed 与
    /// `random_step`，于是抽到的是**同一张**（第一版就是这样，40 次全是同一张 skill，
    /// 而"池子只要 power"那条负控因此**照样绿**）。
    #[test]
    fn dead_branch_adds_a_random_base_card_when_a_card_is_exhausted() {
        use crate::state::{CardZone, EffectRequest, ZonePlacement};

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let hand_of = |state: &crate::state::CombatState| -> Vec<String> {
            state
                .card_zones(&cid("hero"))
                .expect("zones")
                .slots(CardZone::Hand)
                .iter()
                .filter_map(|slot| state.card(crate::state::CardSlot::from_index(*slot)))
                .map(|card| std::string::String::from(card.definition_id.as_str()))
                .collect()
        };
        let exhaust_one = |state: &mut crate::state::CombatState| {
            let card = card_in_hand(state, &content, "hero", "strike");
            state
                .enqueue_effect_with_owner(
                    EffectRequest::MoveCardToZone {
                        owner: cid("hero"),
                        card,
                        to_zone: CardZone::ExhaustPile,
                        placement: ZonePlacement::Bottom,
                    },
                    None,
                )
                .unwrap();
        };

        // ② 没有状态：手牌又空了（消耗掉的那张不会补回来）。
        let mut bare = arena();
        exhaust_one(&mut bare);
        host.try_resolve_pending_queues(&mut bare).expect("triggers");
        assert!(hand_of(&bare).is_empty(), "without the relic nothing comes back");

        // ①③④ 有状态：一次加一张，且池子是任意牌。
        let mut state = arena();
        give(&mut state, "hero", status("st_db", "standard.dead_branch", 1));
        let mut kinds = (false, false, false); // (attack, skill, power)
        for _ in 0..60 {
            let before = hand_of(&state);
            exhaust_one(&mut state);
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            let after = hand_of(&state);
            let added: Vec<&String> =
                after.iter().filter(|definition| !before.contains(definition)).collect();
            assert_eq!(added.len(), 1, "each exhaustion adds exactly one card");
            let added = added[0];
            assert!(!added.contains('+'), "the pool holds base rows only, got `{added}`");
            assert_eq!(
                content.card_has_tag(added, "x_cost"),
                Some(false),
                "and never an X-cost card, got `{added}`"
            );
            kinds.0 |= content.card_has_tag(added, "attack") == Some(true);
            kinds.1 |= content.card_has_tag(added, "skill") == Some(true);
            kinds.2 |= content.card_has_tag(added, "power") == Some(true);
            if kinds.0 && kinds.1 && kinds.2 {
                break;
            }
        }
        assert!(
            kinds.0 && kinds.1 && kinds.2,
            "the pool is *any* base card, so enough draws must cover all three kinds; got \
             attack={} skill={} power={}",
            kinds.0,
            kinds.1,
            kinds.2
        );
    }
'''


def main():
    s = io.open(HOST, encoding='utf-8').read()
    start = s.index('    /// §299：`dead_branch` —— 每**消耗**一张牌')
    # 下一个函数的文档注释起点 = 段末
    end = s.index('    /// §299：`orange_pellets`', start)
    s = s[:start] + CLEAN + '\n' + s[end:]
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(s)
    print('dead_branch test replaced wholesale')


main()
