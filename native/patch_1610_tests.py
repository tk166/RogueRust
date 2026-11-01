"""§161.10: three tests the review asked for, each able to fail on the old code.

1. `resolve_choice` with a **full mark-counter card** must refuse and change nothing (the partial
   commit: `write_price` used to run after `move_card`).
2. `DiscardThenDraw` at the capacity edge must be **allowed** (the old check refused a legal move).
3. An archive taken **after a card was removed** must still round-trip (the old `remove_card` left a
   stale tail slot, so `restored != run`).
"""
import io

STATE = "kernel/rd-core/src/state.rs"
RUN = "kernel/rd-run/src/state/archive.rs"

CORE_TEST = '''    /// **每副本价格写不进去时，选牌必须一张牌都不动**（REVIEW P1，§161.10）。
    ///
    /// 旧实现先 `move_card` 再 `write_price`，而后者会因那张牌自己的计数器表满了而失败 ——
    /// 于是"被拒绝"的选牌已经搬走了一张。判据是 §161.2(a) 的老规矩：**规范文本相等，且问句还在**。
    #[test]
    fn a_choice_that_cannot_write_its_price_moves_nothing() {
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        // 把第一张牌的计数器表塞满（不含 `card_cost_delta`），于是它再也吃不下一个价格。
        let (_, slot) = s.find_card(&cid("hero"), &hand[0]).expect("in hand");
        for index in 0..MAX_MARK_COUNTERS_PER_CARD {
            let key = CounterId::new(std::format!("filler_{index}")).expect("short id");
            s.card_mut(slot)
                .expect("card")
                .set_mark_counter(key, index as i32)
                .expect("counter room");
        }
        assert!(
            !card_can_take_price(s.card(slot).expect("card")),
            "the fixture must actually be full"
        );

        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::ToHand,
            offered: Bounded::new(),
        })
        .unwrap();
        let before = canonical_text(&s);
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), -1),
            Err(ChoiceError::Capacity(CapacityError::Full(
                Container::MarkCounters
            ))),
            "a price that cannot be written must be refused"
        );
        assert_eq!(canonical_text(&s), before, "and nothing may have moved");
        assert_eq!(s.pending_choice().is_some(), true, "the question is still open");
    }

    /// `DelayedThenDraw` 在容量边缘：先丢再抽，手牌最终回到原样 ⇒ **必须允许**。
    ///
    /// 旧的判据是 `hand + picked > MAX_CARDS_PER_ZONE ⇒ 拒绝`，那不是"保守"而是**错**。
    #[test]
    fn discarding_before_drawing_does_not_need_extra_hand_room() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        // 手牌塞到只剩 2 格：选 2 张丢弃之后，手牌空出 2 格，抽 2 张正好填回。
        for index in 0..(MAX_CARDS_PER_ZONE - 2) {
            let id = std::format!("card_{:06}", index + 1);
            s.push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(ciid(&id), cdid("standard.strike")),
            )
            .unwrap();
        }
        for index in 0..4 {
            let id = std::format!("draw_{:06}", index + 1);
            s.push_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardInstance::new(ciid(&id), cdid("standard.defend")),
            )
            .unwrap();
        }
        let hand_before = s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand);
        assert!(hand_before + 2 > MAX_CARDS_PER_ZONE, "the fixture must be at the edge");
        let picks = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 0,
            max: 2,
            then: ChoiceThen::DiscardThenDraw,
            offered: Bounded::new(),
        })
        .unwrap();
        let done = s.resolve_choice(ChoiceAnswer::Instances(&picks[..2]), 0).expect(
            "discarding two cards frees exactly the two slots the draw needs -- this must be legal",
        );
        assert_eq!(done.picked, 2);
        assert_eq!(done.drawn, 2);
        assert_eq!(
            s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand),
            hand_before,
            "two out, two in"
        );
    }

'''

ARCHIVE_TEST = '''    /// **删过牌的局也要能整局相等地回档**（REVIEW P1，§161.10）。
    ///
    /// 旧 `remove_card` 把尾槽留着（`deck()` 看不见，但结构里还在），而存档只写前 `deck_len` 项
    /// ⇒ 回档后 `restored != run`。这条测试先删一张牌再存档，于是它能在旧实现上失败。
    #[test]
    fn a_run_that_lost_a_card_still_round_trips() {
        let mut run = sample();
        // 删除服务只在商店里可用：走进去，买掉最便宜的一项服务。
        let pool = [rd_run::state::PoolCard {
            id: "strike".to_string().leak(),
            rarity: rd_run::state::Rarity::Common,
        }];
        run.adjust_gold(400);
        assert!(walk_to_shop(&mut run), "the map must have a shop for this fixture");
        run.begin_node(&pool, &[]).expect("stock the shop");
        let before = run.deck().len();
        run.remove_card(1).expect("removal service");
        assert_eq!(run.deck().len(), before - 1);

        let mut out = [0u8; MAX_ARCHIVE];
        let len = write(&run, &mut out).expect("write");
        let text = core::str::from_utf8(&out[..len]).expect("ascii");
        let mut restored = RunState::new_with_ascension(1, 80, 0, &[], 0).expect("a skeleton");
        restore(text, &mut restored).expect("restore");
        assert_eq!(restored, run, "a removed card left the archive unable to round-trip");
    }

    fn walk_to_shop(run: &mut RunState) -> bool {
        for target in 0..200u16 {
            if run.enter_node(target as u8).is_err() {
                continue;
            }
            if run.node_kind() == Some(rd_run::map::NodeKind::Shop) {
                return true;
            }
            run.mark_resolved();
        }
        false
    }

'''


def main():
    state = io.open(STATE, encoding="utf-8").read()
    anchor = "    #[test]\n    fn an_offered_choice_creates_only_the_card_that_was_picked() {"
    assert state.count(anchor) == 1, state.count(anchor)
    assert "a_choice_that_cannot_write_its_price" not in state, "already inserted"
    io.open(STATE, "w", encoding="utf-8", newline="").write(
        state.replace(anchor, CORE_TEST + anchor)
    )

    run = io.open(RUN, encoding="utf-8").read()
    anchor2 = "    #[test]\n    fn an_edited_or_truncated_archive_is_refused_not_guessed() {"
    assert run.count(anchor2) == 1, run.count(anchor2)
    assert "a_run_that_lost_a_card_still_round_trips" not in run, "already inserted"
    io.open(RUN, "w", encoding="utf-8", newline="").write(
        run.replace(anchor2, ARCHIVE_TEST + anchor2)
    )
    print("three falsifiable tests added")


if __name__ == "__main__":
    main()
