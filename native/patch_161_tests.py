"""Append the §161.3 tests to rd-core's state.rs test module.

One shot: the anchor is the end of `moving_a_card_reuses_its_pool_slot...`, and the guard asserts
that no choice test is there yet.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """        // 1000 轮之后分布仍然正确：弃牌堆 10 张，其它为空。
        let z = s.card_zones(&hero).unwrap();
        assert_eq!(z.count(CardZone::DiscardPile), 10);
        assert_eq!(z.count(CardZone::DrawPile), 0);
        assert_eq!(z.count(CardZone::Hand), 0);
    }
"""

TESTS = """        // 1000 轮之后分布仍然正确：弃牌堆 10 张，其它为空。
        let z = s.card_zones(&hero).unwrap();
        assert_eq!(z.count(CardZone::DiscardPile), 10);
        assert_eq!(z.count(CardZone::DrawPile), 0);
        assert_eq!(z.count(CardZone::Hand), 0);
    }

    // ── 待决的选牌（§161.3）────────────────────────────────────────────────────────────────────
    //
    // 这一组测试盯的是 REVIEW §四.2 的那句话：机制要「可枚举、可存档、可回放」。
    // 所以除了"选完真的动了牌"，还各有一条钉住**枚举**（`choice_legal` 的顺序与截断）
    // 与**拒绝的原子性**（§161.2(a) 在战斗层的同一条话）。

    fn hand_of(n: usize) -> CombatState {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for i in 0..n {
            let id = std::format!("card_{:06}", i + 1);
            s.push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(ciid(&id), cdid("standard.strike")),
            )
            .unwrap();
        }
        s
    }

    /// 一个牌区的卡实例 id，按牌堆顺序。**从状态派生**，不自己记。
    fn pile_ids(s: &CombatState, zone: CardZone) -> std::vec::Vec<CardInstanceId> {
        let zones = s.card_zones(&cid("hero")).unwrap();
        (0..zones.count(zone))
            .filter_map(|index| zones.slot_at(zone, index))
            .filter_map(|slot| s.card(slot))
            .map(|card| card.id)
            .collect()
    }

    fn elixir(min: u8, max: u8) -> PendingChoice {
        PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min,
            max,
            then: ChoiceThen::Exhaust,
        }
    }

    fn gamblers_brew(max: u8) -> PendingChoice {
        PendingChoice {
            then: ChoiceThen::DiscardThenDraw,
            ..elixir(0, max)
        }
    }

    #[test]
    fn the_legal_options_are_the_source_pile_in_pile_order() {
        let mut s = hand_of(3);
        // 没有待决问句时，枚举是**一个错误**，不是"空清单" —— 空清单会被读成
        // "可以选的东西是零个"，而那是一个不存在的状态。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Err(ChoiceError::NotPending));

        s.begin_choice(elixir(0, 3)).unwrap();
        assert_eq!(s.choice_legal(&mut buf), Ok(3));
        assert_eq!(
            &buf[..3],
            pile_ids(&s, CardZone::Hand).as_slice(),
            "候选清单必须就是来源牌区，且顺序与牌堆一致"
        );

        // 缓冲区装不下 ⇒ 响亮失败，**不截断**。截断掉的选项等于一条不存在的规则，而
        // 「只能选前两张」这种错只会在玩家真的想选第三张时才被发现。
        let mut tiny = [CardInstanceId::EMPTY; 2];
        assert_eq!(
            s.choice_legal(&mut tiny),
            Err(ChoiceError::Capacity(CapacityError::Full(
                Container::ChoiceOptions
            )))
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 3)), "枚举失败不改问句");
    }

    #[test]
    fn exhausting_the_chosen_cards_moves_exactly_them_and_clears_the_question() {
        // Elixir：「消耗任意张手牌」。选 2 张。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 3)).unwrap();
        let done = s.resolve_choice(&[hand[0], hand[2]]).unwrap();
        assert_eq!(done, ChoiceDone { picked: 2, drawn: 0 });
        assert_eq!(s.pending_choice(), None, "结算之后问句必须消失");

        assert_eq!(
            pile_ids(&s, CardZone::ExhaustPile),
            std::vec![hand[0], hand[2]],
            "被选中的两张按选择顺序进消耗堆"
        );
        assert_eq!(pile_ids(&s, CardZone::Hand), std::vec![hand[1]], "没被选的必须留手");
    }

    #[test]
    fn discarding_then_drawing_returns_as_many_cards_as_were_dropped() {
        // Gambler's Brew：「弃任意张，然后抽同样多」。
        let mut s = hand_of(3);
        for i in 0..4 {
            let id = std::format!("draw_{:06}", i + 1);
            s.push_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardInstance::new(ciid(&id), cdid("standard.defend")),
            )
            .unwrap();
        }
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(gamblers_brew(3)).unwrap();
        let done = s.resolve_choice(&[hand[0], hand[1]]).unwrap();
        assert_eq!(done, ChoiceDone { picked: 2, drawn: 2 });
        assert_eq!(pile_ids(&s, CardZone::DiscardPile), std::vec![hand[0], hand[1]]);
        assert_eq!(s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand), 3);
        // 抽到的是**抽牌堆的最上面两张**（`draw_card` 取 front），顺序照抄。
        assert_eq!(
            pile_ids(&s, CardZone::Hand),
            std::vec![hand[2], ciid("draw_000001"), ciid("draw_000002")]
        );
        // 抽牌堆少了 2 张，弃牌堆多了 2 张 —— 池子不长（移动复用槽位）。
        assert_eq!(s.card_count(), 7);
    }

    #[test]
    fn drawing_past_an_empty_draw_pile_reshuffles_like_the_turn_start_does() {
        // 抽牌堆空、弃牌堆有牌 ⇒ 必须走 `reshuffle_discard_into_draw`（一次，且推进 random_step）。
        // 不做这一步的话"弃 2 抽 2"会安静地只抽到 0 张 —— 那看起来像是玩家选错了。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        let step_before = s.random_step;
        s.begin_choice(gamblers_brew(3)).unwrap();
        let done = s.resolve_choice(&[hand[0], hand[1]]).unwrap();
        assert_eq!(done.picked, 2);
        // 弃牌堆里的 2 张被洗回抽牌堆，于是这 2 张**又**被抽了回来。
        assert_eq!(done.drawn, 2, "重洗之后抽得满");
        assert_eq!(s.random_step, step_before + 1, "重洗推进一次随机步");
    }

    #[test]
    fn a_refused_choice_leaves_the_combat_byte_identical() {
        // §161.2(a) 在战斗层的同一条话：拒绝 ⇒ 一个字节都没改。
        //
        // 判据用规范文本（`canonical_text`），因为 `CombatState` 没有派生 `PartialEq`
        // （18 个字段里有 6 个定容容器，逐字段写一份"等价"没法确认自己没漏）。
        // ⚠️ 规范文本**不含** `choice` 本身（参考引擎没有这个字段，见 §161.3 的文档），
        // 所以下面每一种拒绝都额外断言 `pending_choice()` 没变 —— 两边都看才完整。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(1, 2)).unwrap();
        let before = canonical_text(&s);
        let before_choice = s.pending_choice();

        let refused = [
            // (a) 张数：0 张低于下限 1、3 张高于上限 2。
            (
                s.clone().resolve_choice(&[]),
                ChoiceError::Count {
                    picked: 0,
                    min: 1,
                    max: 2,
                },
            ),
            (
                s.clone()
                    .resolve_choice(&[hand[0], hand[1], hand[2]]),
                ChoiceError::Count {
                    picked: 3,
                    min: 1,
                    max: 2,
                },
            ),
            // (b) 来源：库里没有这张牌。
            (
                s.clone().resolve_choice(&[ciid("not_a_card")]),
                ChoiceError::NotInSource,
            ),
            // (c) 重复：同一张选两次。
            (
                s.clone().resolve_choice(&[hand[0], hand[0]]),
                ChoiceError::Duplicate,
            ),
        ];
        for (outcome, expected) in refused {
            assert_eq!(outcome, Err(expected), "拒绝原因必须具体");
        }

        // 真·原子性：**不是**用 `s.clone()` 试错，而是在真身上走一遍再比。
        assert_eq!(s.resolve_choice(&[hand[0], hand[0]]), Err(ChoiceError::Duplicate));
        assert_eq!(canonical_text(&s), before, "被拒绝的选牌改了战斗");
        assert_eq!(s.pending_choice(), before_choice, "被拒绝的选牌改了问句");

        // 一张已经不在来源牌区里的牌：先把它丢掉，再从手牌里选它。
        let mut moved = hand_of(3);
        let hand = pile_ids(&moved, CardZone::Hand);
        moved
            .move_card(
                &cid("hero"),
                CardZone::Hand,
                CardZone::DiscardPile,
                CardSlot::from_index(0),
                ZonePlacement::Bottom,
            )
            .unwrap();
        moved.begin_choice(elixir(0, 2)).unwrap();
        let before = canonical_text(&moved);
        assert_eq!(
            moved.resolve_choice(&[hand[0]]),
            Err(ChoiceError::NotInSource),
            "来源是手牌，选一张弃牌堆里的牌必须被拒"
        );
        assert_eq!(canonical_text(&moved), before);
    }

    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {
        // `min` 超过来源牌区的张数 ⇒ 这个问句永远无法回答。把它放行的话，这一局会被一个
        // 玩家答不出来的弹窗钉死，而内核里没有任何东西会报错 —— 正是本项目最怕的那种形态。
        let mut s = hand_of(2);
        assert_eq!(
            s.begin_choice(elixir(3, 3)),
            Err(ChoiceError::Count {
                picked: 2,
                min: 3,
                max: 3,
            })
        );
        assert_eq!(s.pending_choice(), None, "被拒绝的问句不许留下");

        // `min > max` 是内容错误（不是玩家输入错误），同样响亮。
        assert_eq!(
            s.begin_choice(elixir(2, 1)),
            Err(ChoiceError::Count {
                picked: 2,
                min: 2,
                max: 1,
            })
        );

        // 选 0 张（下限 0）是合法答案，而且**真的**把问句消掉 —— 这就是"取消"。
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(s.resolve_choice(&[]), Ok(ChoiceDone { picked: 0, drawn: 0 }));
        assert_eq!(s.pending_choice(), None);
    }

    #[test]
    fn a_second_choice_is_refused_instead_of_queued() {
        // 不排队：两个待决问句叠在一起，界面无法表达先后，回放也无法表达。
        let mut s = hand_of(2);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.begin_choice(gamblers_brew(2)),
            Err(ChoiceError::AlreadyPending),
            "第二个问句必须被拒，而不是覆盖或排队"
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "第一个问句原样留下");
    }
"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn elixir(" not in text, "already inserted"
    text = text.replace(ANCHOR, TESTS)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("tests inserted")


if __name__ == "__main__":
    main()
