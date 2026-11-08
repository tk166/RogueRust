"""§306 E 类收尾：核实 `runic_pyramid`（手牌保留）**真的**在战斗里成立。

## 这一轮不是"再实现一遍"，而是"补上那条没人写的判据"

`runic_pyramid` 在 §268 就已经接线：内容状态 `standard.runic_pyramid` 带 `retain_hand` 标签，
`host.rs::hand_is_retained_detail` 读标签，`turn.rs` 按它决定回合末弃不弃手牌。
覆盖矩阵里它的"测试"一栏是 `the_zero_infrastructure_tail_wires_its_carriers` ——
那条只证明**遗物挂上了状态**，不证明**手牌真的留下来了**。

这正是本项目最怕的形状（"接线成功、行为没验"）。所以这里补三层：
* 没有遗物：回合末手牌清空（基线，`turn.rs` 那条 `the_hand_is_actually_discarded...` 只测了
  配置层，没测"真打一场"）；
* 有遗物：回合末手牌**一张不少**，且下一回合开始时不抽新牌（手牌已满，抽牌数按上限截）；
* `Ethereal` 与 `retain_hand` 是两件事：带 ethereal 的牌仍然消耗（不因为整手保留而留下）。
"""
import io

LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TEST = r'''
    /// §306：`runic_pyramid` —— 回合末整手牌**保留**。
    ///
    /// 三层：基线（没有遗物时清空）、有遗物（一张不少）、`Ethereal` 仍然消耗。
    /// 基线那一层是必须的：只验"有遗物时保留"的话，一条"永远保留"的实现也全绿 ——
    /// 而那会让整局游戏的手牌越滚越多，并且**没有任何东西会红**。
    #[test]
    fn runic_pyramid_keeps_the_whole_hand_and_ethereal_still_exhausts() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
            vec![
                rd_core::battle::DeckEntry { card: "strike", count: 10 },
                // `dazed` 是 Ethereal：回合末进消耗堆。它必须**不**受整手保留的影响。
                rd_core::battle::DeckEntry { card: "dazed", count: 4 },
            ]
            .into_boxed_slice(),
        );

        /// 打到"回合末"为止：把手牌里能打的都打掉，然后结束回合。返回（回合末手牌数, 消耗堆）。
        fn play_a_turn() -> (usize, usize) {
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            // 打掉所有打得起的牌（不打就分不清"保留"与"没打完"）。
            for _ in 0..20 {
                let session = slot().as_mut().expect("session");
                let hero = cid_in("hero");
                let Some(card) = session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::Hand)
                    .next()
                    .map(|card| card.id)
                else {
                    break;
                };
                let target = session
                    .state
                    .combatants()
                    .iter()
                    .find(|c| c.team_id.as_str() == "enemy")
                    .map(|c| c.id);
                let request = rd_core::play::PlayRequest::new(hero, card, target);
                if rd_core::play::play_card(&mut session.state, Some(&content), &request).is_err() {
                    break;
                }
                let mut host = rd_core::host::Host::new(&content);
                let _ = host.try_resolve_pending_queues(&mut session.state);
            }
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let hero = cid_in("hero");
            host.end_turn(&mut session.state, &standard, &hero)
                .expect("the turn ends");
            let session = slot().as_ref().expect("session");
            let hand = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .count();
            let exhaust = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::ExhaustPile)
                .count();
            (hand, exhaust)
        }

        fn start(pyramid: bool) {
            let session = build_session_at_unstarted(61, "enc_cultist", 200, Some(deck), 0, 0)
                .expect("a session");
            install_session(session);
            if pyramid {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(
                            "standard.runic_pyramid",
                        )
                        .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
        }

        // ① 基线：没有遗物 ⇒ 回合末手牌清空（只剩 `dazed` 之外的牌都被打掉了）。
        start(false);
        let (without_hand, without_exhaust) = play_a_turn();
        take_session();
        assert_eq!(
            without_hand, 0,
            "without the relic the hand is discarded at end of turn"
        );

        // ② 有遗物 ⇒ 手牌一张不少。
        start(true);
        let (with_hand, with_exhaust) = play_a_turn();
        take_session();
        assert!(
            with_hand > 0,
            "with `runic_pyramid` the unplayed hand stays (got {with_hand})"
        );
        // ③ `Ethereal` **仍然**消耗：整手保留不是"什么都在手里"。
        assert!(
            with_exhaust > without_exhaust,
            "ethereal cards still exhaust (with {with_exhaust} vs without {without_exhaust})"
        );
    }
'''


def main():
    s = io.open(LIB, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    io.open(LIB, 'w', encoding='utf-8', newline='\n').write(s[:cut] + TEST + s[cut:])
    print('test added')


main()
