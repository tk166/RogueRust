"""§320 判据 —— 事件候选列表（`the_library` / `sensory_stone`）。

六条：
1. 摊出来的是 **n 张互不相同、且口径正确** 的候选（无色池只给无色牌）；
2. 取走一张 ⇒ 进牌组，且**三个蛋生效**（`molten_egg` 给 Attack 升级 —— wiki："non-upgraded
   unless you have Toxic Egg / Molten Egg / Frozen Egg"）；
3. 池子凑不出 n 张 ⇒ 拒绝（`PoolTooSmall`），**整个 RunState 不变**；
4. 候选**占的是同一个待答位置**：一条选项里既 offer 又改牌 ⇒ `TwoDeckChanges`，一个字节不改；
5. **先进存档、再读回来**：候选表与"选哪张"都在里面（`Pending::EventOffer` 也是）；
6. 候选进了指纹：20 选 1 的两组不同候选不能哈希成同一串。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
ANCHOR = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

TESTS = '''    /// §320：一张带 `colorless` 标记的池子 —— `Sensory Stone` 只从这一半抽。
    ///
    /// 8 张：5 张无色（三种稀有度）、3 张不是。候选张数取 3 时，"抽到有色牌"会当场红。
    fn offer_pool() -> [PoolCard<'static>; 8] {
        [
            PoolCard { id: "swift_strike", rarity: Rarity::Uncommon, kind: CardKind::Attack,
                       upgraded: None, colorless: true },
            PoolCard { id: "apparition", rarity: Rarity::Rare, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
            PoolCard { id: "blind", rarity: Rarity::Uncommon, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
            PoolCard { id: "dark_shackles", rarity: Rarity::Uncommon, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
            PoolCard { id: "purity", rarity: Rarity::Uncommon, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack,
                       upgraded: Some("strike+"), colorless: false },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill,
                       upgraded: None, colorless: false },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Attack,
                       upgraded: None, colorless: false },
        ]
    }

    fn colorless_of(pool: &[PoolCard<'static>]) -> Vec<&'static str> {
        pool.iter().filter(|card| card.colorless).map(|card| card.id).collect()
    }

    /// §320：`[Recall]` 摊开 3 张**无色**候选；取走一张 ⇒ 进牌组。
    #[test]
    fn an_event_offer_shows_distinct_cards_of_the_named_pool() {
        let pool = offer_pool();
        let allowed = colorless_of(&pool);
        let mut run = RunState::new(7, 80, 0, &["strike", "defend"]).expect("a run");
        run.begin_event("sensory_stone", "sensory_stone").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::OfferCards(3, OfferFilter::Colorless), None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("offering three colorless cards");

        assert_eq!(run.pending(), Pending::EventOffer, "the run waits for a pick");
        assert_eq!(run.event_offer_len(), 3, "three candidates");
        let mut seen: Vec<&str> = Vec::new();
        for slot in 0..run.event_offer_len() {
            let id = run.event_offer_card(slot).expect("a candidate");
            assert!(allowed.contains(&id), "{id} is not colorless");
            assert!(!seen.contains(&id), "{id} appears twice");
            seen.push(id);
        }

        let deck_before = run.deck_len;
        run.pick_event_offer(0, &pool).expect("taking the first candidate");
        assert_eq!(run.deck_len, deck_before + 1, "it went into the deck");
        assert_eq!(run.pending(), Pending::None, "and the choice is done");
        assert_eq!(run.event_offer_len(), 0, "the offer is cleared");
        let last = run.deck()[run.deck_len as usize - 1].as_str();
        assert_eq!(last, seen[0], "the card taken is the one that was shown");
    }

    /// §320：`OfferFilter::Any` 不筛（`The Library`），而且**互不相同**（同一张不许给两次）。
    #[test]
    fn the_any_filter_takes_the_whole_pool_without_repeats() {
        let pool = offer_pool();
        let mut run = RunState::new(3, 80, 0, &["strike"]).expect("a run");
        run.begin_event("the_library", "the_library").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::OfferCards(7, OfferFilter::Any), None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("offering the whole pool");
        assert_eq!(run.event_offer_len(), 7, "seven of the eight");
        let mut seen: Vec<&str> = Vec::new();
        for slot in 0..7 {
            let id = run.event_offer_card(slot).expect("a candidate");
            assert!(!seen.contains(&id), "{id} appears twice");
            seen.push(id);
        }
    }

    /// §320：池子凑不出承诺的张数 ⇒ **拒绝**，一个字节不改。
    ///
    /// 这是"内容写错了"的形状：`offer_cards:20:colorless` 在只有 5 张无色牌的池子上
    /// 必须响亮地失败，而不是摊出 5 张然后让玩家以为"就是这些"。
    #[test]
    fn an_offer_larger_than_the_pool_is_refused() {
        let pool = offer_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        run.begin_event("the_library", "the_library").expect("the event");
        let before = run;
        assert_eq!(
            run.resolve_event_effects(
                &EventMove {
                    effects: &[(EventEffect::OfferCards(9, OfferFilter::Colorless), None)],
                    ..EventMove::none()
                },
                &pool,
            ),
            Err(RunError::PoolTooSmall { pool: 5, need: 9 }),
            "only five colorless cards exist in the fixture"
        );
        assert!(run == before, "not one byte moved");
    }

    /// §320：候选与改牌**抢同一个位置** ⇒ 一条选项里两个都有就是内容错误。
    #[test]
    fn an_offer_and_a_deck_edit_cannot_share_one_choice() {
        let pool = offer_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        run.begin_event("the_library", "the_library").expect("the event");
        let before = run;
        assert_eq!(
            run.resolve_event_effects(
                &EventMove {
                    effects: &[
                        (EventEffect::RemoveCard, None),
                        (EventEffect::OfferCards(3, OfferFilter::Any), None),
                    ],
                    ..EventMove::none()
                },
                &pool,
            ),
            Err(RunError::TwoDeckChanges),
            "one waiting question, one slot"
        );
        assert!(run == before, "not one byte moved");
    }

    /// §320：候选表**进存档**（含 `Pending::EventOffer`）—— 读回来还能接着选。
    #[test]
    fn the_offer_survives_a_save_and_a_hash() {
        let pool = offer_pool();
        let mut run = ironclad();
        run.begin_event("sensory_stone", "sensory_stone").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::OfferCards(2, OfferFilter::Colorless), None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("offering two");
        let shown = [run.event_offer_card(0).expect("first"), run.event_offer_card(1).expect("second")];
        let baseline = crate::hash::run_hash(&run).expect("a hash");

        let mut buf = [0u8; crate::state::archive::MAX_ARCHIVE];
        let len = crate::state::archive::write(&run, 7, &mut buf).expect("write");
        let text = std::str::from_utf8(&buf[..len]).expect("ascii");
        let mut restored = ironclad();
        crate::state::archive::restore(text, 7, &mut restored).expect("read");
        assert_eq!(restored.pending(), Pending::EventOffer, "the offer is still open");
        assert_eq!(restored.event_offer_len(), 2, "two candidates come back");
        assert_eq!(restored.event_offer_card(0), Some(shown[0]));
        assert_eq!(restored.event_offer_card(1), Some(shown[1]));
        assert_eq!(crate::hash::run_hash(&restored).expect("a hash"), baseline, "hash round-trips");

        // 反过来：换掉一张候选 ⇒ 指纹必须不同（"忘了把候选写进规范文本"会看不出来）。
        let mut other = restored.clone();
        other.event_offer[0] = RunId::new("strike").expect("an id");
        assert_ne!(
            crate::hash::run_hash(&other).expect("a hash"),
            baseline,
            "the candidate list is part of the fingerprint"
        );
    }

    /// §320：取牌时**三个蛋**生效 —— `molten_egg` 让 Attack 以 `+` 行进牌组（wiki 明写）。
    #[test]
    fn taking_an_offer_applies_the_egg_relics() {
        let pool = offer_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        run.push_relic("molten_egg", &TYPED_CARDS).expect("molten egg");
        run.begin_event("the_library", "the_library").expect("the event");
        // 只摊一张，而且是 `strike`（Attack，池子里有 `strike+`）。
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::OfferCards(1, OfferFilter::Any), None)],
                ..EventMove::none()
            },
            &[pool[5]],
        )
        .expect("offering the attack");
        assert_eq!(run.event_offer_card(0), Some("strike"));
        run.pick_event_offer(0, &pool).expect("taking it");
        assert_eq!(
            run.deck()[run.deck_len as usize - 1].as_str(),
            "strike+",
            "molten_egg upgrades an offered Attack as it enters the deck"
        );
    }

'''


def main():
    t = io.open(STATE, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn an_event_offer_shows_distinct_cards_of_the_named_pool' not in t, 'already patched'
    t = t.replace(ANCHOR, TESTS + ANCHOR)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
    print('§320 tests inserted')


main()
