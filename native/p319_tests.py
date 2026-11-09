"""§319：`falling` 的运行层判据。

四条：
1. **删的是那个类型**（技能）；牌组尺寸 -1，且剩下的牌全都还在池子里。
2. **没有该类型的牌 ⇒ 拒绝**，而且是整个 `RunState` 一个字节都没动（`RunState: Copy + Eq`）。
3. **随机、且只掷一次 Event 流**：同一个种子两次跑出同一副牌（源流不进战斗流）。
4. **词表**：`remove_card_random:skill` 能解析，`remove_card_random:powerr` / `skill:` 空载荷
   **解析失败**（拼错的类型绝不能变成 `Other`）。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'

ANCHOR = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

TESTS = '''    /// §319：一张带**真类型**的池子 —— 既有的 `basic_pool()` / `curse_pool()` 全是
    /// `CardKind::Other`，而 `falling` 判的就是类型，用它们等于判"删了一张牌"。
    fn kind_pool() -> [PoolCard<'static>; 4] {
        [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: None },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: None },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: None },
            PoolCard { id: "ascenders_bane", rarity: Rarity::Curse, kind: CardKind::Curse, upgraded: None },
        ]
    }

    fn count_of(run: &RunState, id: &str) -> usize {
        run.deck().iter().filter(|card| card.as_str() == id).count()
    }

    /// §319：`falling` 的 `[Land] Lose (a random Skill)` —— 删掉的是**那个类型**的一张。
    ///
    /// 为什么判"是技能"而不是"少了一张"：`remove_at(0)` 也能让尺寸变，那正是这个原子
    /// 最可能退化成的东西（把 `kind` 忽略掉）。牌组里两种类型都有，所以退化的实现在这里红。
    #[test]
    fn falling_removes_a_card_of_the_named_kind() {
        let pool = kind_pool();
        let mut run = RunState::new(7, 80, 0, &["strike", "defend", "bash", "defend"])
            .expect("a run");
        run.begin_event("falling", "falling").expect("opening the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::RemoveCardRandom(CardKind::Skill), None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("losing a random Skill");

        assert_eq!(run.deck_len, 3, "one card is gone");
        assert_eq!(count_of(&run, "defend"), 1, "exactly one Skill was removed");
        assert_eq!(count_of(&run, "strike") + count_of(&run, "bash"), 2, "no Attack was touched");
        for card in run.deck() {
            assert!(
                pool.iter().any(|entry| entry.id == card.as_str()),
                "the deck holds {:?}, which is not in the pool",
                card.as_str()
            );
        }
    }

    /// §319：牌组里一张该类型的牌都没有 ⇒ **拒绝**，并且一个字节都不改。
    ///
    /// 这是 `[Channel]` 在本内容里的处境（0 张 power 牌）：内容那条选项会被
    /// `card_tag` 条件藏起来，所以走到这里只有一种解释 —— 条件与效果对不上。
    #[test]
    fn falling_refuses_when_the_kind_is_absent() {
        let pool = kind_pool();
        let mut run = RunState::new(7, 80, 0, &["strike", "defend", "bash"])
            .expect("a run");
        run.begin_event("falling", "falling").expect("opening the event");
        let before = run;

        assert_eq!(
            run.resolve_event_effects(
                &EventMove {
                    effects: &[(EventEffect::RemoveCardRandom(CardKind::Power), None)],
                    ..EventMove::none()
                },
                &pool,
            ),
            Err(RunError::NoEligibleCard),
            "no Power in the deck -- the effect must refuse, not silently do nothing"
        );
        assert!(run == before, "not one byte moved");
    }

    /// §319：同一个种子 ⇒ 同一张牌被删（掷的是 `RunStream::Event`，是可复现的）。
    #[test]
    fn falling_is_deterministic_for_a_seed() {
        let pool = kind_pool();
        let deck = ["strike", "defend", "defend", "bash", "defend"];
        let mut first = RunState::new(11, 80, 0, &deck).expect("a run");
        let mut second = RunState::new(11, 80, 0, &deck).expect("a run");
        for run in [&mut first, &mut second] {
            run.begin_event("falling", "falling").expect("the event");
            run.resolve_event_effects(
                &EventMove {
                    effects: &[(EventEffect::RemoveCardRandom(CardKind::Skill), None)],
                    ..EventMove::none()
                },
                &pool,
            )
            .expect("losing a random Skill");
        }
        assert!(first == second, "the same seed must lose the same card");
    }

    /// §319：词表 —— 拼错的类型**解析失败**，不退回 `Other`。
    #[test]
    fn remove_card_random_takes_a_kind_and_refuses_a_typo() {
        assert_eq!(
            EventEffect::parse("remove_card_random:skill", 0),
            Some((EventEffect::RemoveCardRandom(CardKind::Skill), None))
        );
        assert_eq!(
            EventEffect::parse("remove_card_random:power", 0),
            Some((EventEffect::RemoveCardRandom(CardKind::Power), None))
        );
        // 拼错 / 空载荷 / 陌生名字：三种都必须 `None`（`Other` 会让它删错牌）。
        assert_eq!(EventEffect::parse("remove_card_random:powerr", 0), None);
        assert_eq!(EventEffect::parse("remove_card_random:", 0), None);
        assert_eq!(EventEffect::parse("remove_card_random:", 0), None);
        // 裸词仍然是**改牌问句**，不是这个原子（两者不是同一条路）。
        assert_eq!(EventEffect::parse("remove_card", 0), Some((EventEffect::RemoveCard, None)));
    }

'''


def main():
    t = io.open(STATE, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn falling_removes_a_card_of_the_named_kind' not in t, 'already patched'
    t = t.replace(ANCHOR, TESTS + ANCHOR)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
    print('tests inserted')


main()
