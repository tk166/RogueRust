"""§246 判据：`chooseCards.DrawFirst`（Thinking Ahead / Warcry 的抽牌必须进候选）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §245：`Apotheosis` —— **全部牌区**的牌都升级'

TESTS = r'''    /// §246：`Thinking Ahead` —— **先抽 2 张，再问**，选中的那张回到抽牌堆**顶**。
    ///
    /// 两段：
    /// ① 抽到的两张**在候选里**（这是 `DrawFirst` 存在的全部理由 —— 写成
    ///    `sequence[drawCards, chooseCards]` 时候选快照发生在抽牌落地之前，抽到的牌永远不在候选里）；
    /// ② 选中的那张是抽牌堆的**第一张**（`Placement::Top`，"下一张就抽它"）。
    #[test]
    fn thinking_ahead_draws_first_and_puts_the_card_on_top() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        for index in 0..3 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_d{index}"), "defend", None);
        }
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "thinking_ahead", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("thinking ahead is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("it asks which card goes back");
        assert_eq!(choice.source.zone(), Some(CardZone::Hand), "candidates come from the hand");
        assert_eq!(choice.then, crate::state::ChoiceThen::ToDrawPileTop, "and it goes on top");
        // ① "抽到的牌在候选里"由 `resolve_choice` 自己证明：它会校验选中的实例**在候选表里**
        //    （`state.rs` 的 `candidates.contains(id)`），不在就 `WrongAnswer`。
        //    所以下面这一步成功 == 抽到的牌确实是候选 —— 比数一遍候选更硬。

        // ② 选 `card_d0`，它必须成为抽牌堆的第一张。
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .find(|card| card.id.as_str() == "card_d0")
            .expect("card_d0 is in hand")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let top = state
            .zone_cards(&cid("hero"), CardZone::DrawPile)
            .next()
            .map(|card| card.id.as_str().to_owned());
        assert_eq!(top.as_deref(), Some("card_d0"), "the chosen card is on top");
    }

    /// §246：`Warcry` 的既有隐患 —— 抽到的那张**必须**是候选（"放回堆顶"的牌通常就是它）。
    ///
    /// 这条是**回归判据**：Warcry 原来写的是 `sequence[drawCards(1), chooseCards]`，抽牌只是入队，
    /// 候选快照发生在它落地之前 ⇒ 抽到的那张不在候选里；手牌本来就空时（只有 Warcry 自己）
    /// 连问句都不出现（§236 那个死锁的近亲）。修法是把抽牌搬进问句节点（`DrawFirst`）。
    #[test]
    fn warcry_offers_the_card_it_just_drew() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // 手牌只有 Warcry，抽牌堆一张 —— 修好之前这里**不会**提问（候选为空）。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_d", "bash", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "warcry", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("warcry is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("warcry must ask (the drawn card is a candidate)");
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .find(|card| card.id.as_str() == "card_d")
            .expect("the drawn card is in hand")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let top = state
            .zone_cards(&cid("hero"), CardZone::DrawPile)
            .next()
            .map(|card| card.id.as_str().to_owned());
        assert_eq!(top.as_deref(), Some("card_d"), "the drawn card went back on top");
        let _ = choice;
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'thinking_ahead_draws_first' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 tests')


main()
