"""rd-core: §161.5's tests for the offered-candidate path."""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {"""

TESTS = '''    #[test]
    fn an_offered_choice_creates_only_the_card_that_was_picked() {
        // §161.5：三张候选里只有被选的那一张**曾经存在**。
        //
        // 反过来的做法（先把三张造成实例放进一个牌区，再扔掉两张）会凭空多出三张牌：
        // `card_num=` 与两张 `aside=` 卡行都会出现在指纹里，而参考引擎那个局面根本没有它们。
        // 这条测试盯的就是"牌池里只多了一张"。
        let mut s = hand_of(1);
        let cards_before = s.card_count();
        let next_number = s.next_card_instance_number;
        s.begin_choice(offered_choice(&["card.anger", "card.bash", "card.cleave"]))
            .unwrap();
        assert_eq!(
            s.choice_offered(),
            Ok(&[
                CardDefinitionId::new("card.anger").unwrap(),
                CardDefinitionId::new("card.bash").unwrap(),
                CardDefinitionId::new("card.cleave").unwrap(),
            ][..]),
            "候选按抽出的顺序，原样可读"
        );
        // 牌区来源的读取器对它必须**响亮拒绝**，而不是返回一个空清单。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Err(ChoiceError::WrongAnswer));
        assert_eq!(s.card_count(), cards_before, "提问本身不造牌");

        let done = s.resolve_choice(ChoiceAnswer::Offered(&[1]), -1).unwrap();
        assert_eq!(done, ChoiceDone { picked: 1, drawn: 0 });
        assert_eq!(s.pending_choice(), None);
        assert_eq!(
            s.card_count(),
            cards_before + 1,
            "只多了一张：没被选的两张从来没存在过"
        );
        assert_eq!(s.next_card_instance_number, next_number + 1, "发号器只动了 1");
        // 造出来的那张用的是**参考的 id 形状**，进的是手牌，带着每副本价格。
        let hand = pile_ids(&s, CardZone::Hand);
        let picked = *hand.last().expect("手牌非空");
        assert_eq!(
            picked.as_str(),
            std::format!("card_{:06}", next_number),
            "`card_%06d` 且先取号再自增"
        );
        let (_, slot) = s.find_card(&cid("hero"), &picked).expect("在手牌里");
        let card = s.card(slot).expect("卡在");
        assert_eq!(card.definition_id.as_str(), "card.bash", "选的是第 2 张候选");
        let price = card
            .mark_counters()
            .iter()
            .find(|counter| counter.key.as_str() == CARD_COST_DELTA_COUNTER)
            .map(|counter| counter.value);
        assert_eq!(price, Some(-1), "每副本价格也写上了");

        // 候选来源的问句读完了就没了：`choice_offered` 回到"没有待决问句"。
        assert_eq!(s.choice_offered(), Err(ChoiceError::NotPending));
    }

    #[test]
    fn an_offered_choice_and_a_pile_choice_cannot_answer_each_other() {
        // 两种答案形状不能互换 —— 否则"从手牌选"会拿着三个候选下标去查手牌，
        // 而结果**看起来像成功**（0 张或别的一张）。形状不匹配必须响。
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Offered(&[0]), 0),
            Err(ChoiceError::WrongAnswer)
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "拒绝不改问句");

        let mut offered = hand_of(1);
        offered
            .begin_choice(offered_choice(&["card.anger", "card.bash", "card.cleave"]))
            .unwrap();
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), 0),
            Err(ChoiceError::WrongAnswer)
        );
        // 越界的下标也要响，不能悄悄换成别的候选。
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Offered(&[3]), 0),
            Err(ChoiceError::NotInSource)
        );
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Offered(&[0, 0]), 0),
            Err(ChoiceError::Duplicate)
        );
    }

    #[test]
    fn a_choice_that_has_candidates_must_not_also_name_a_pile() {
        // 「候选」与「来源」不一致 = 一个玩家答不出来的问题。两边都校验。
        let mut s = hand_of(2);
        let mut wrong = offered_choice(&["card.anger"]);
        wrong.source = ChoiceSource::Hand;
        assert_eq!(s.begin_choice(wrong), Err(ChoiceError::WrongAnswer));
        let mut wrong = elixir(0, 2);
        wrong.offered = offered_choice(&["card.anger"]).offered;
        assert_eq!(s.begin_choice(wrong), Err(ChoiceError::WrongAnswer));
        assert_eq!(s.pending_choice(), None, "被拒绝的问句一个都不留");
    }

    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn an_offered_choice_creates_only_the_card" not in text, "already inserted"
    text = text.replace(ANCHOR, TESTS)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: §161.5 tests")


if __name__ == "__main__":
    main()
