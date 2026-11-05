"""§227 (part 5): 把 §226 的那条 state 判据搬到新变体上，并补 `Upgrade` / `ToDrawPileTop`。

`Copy { copies, into }` 之后，"副本数与 then 不自洽"那种校验**不再需要**（非法组合构造不出来），
但它留下的两个真判据还要在：`copies: 0` 必须被拒、收窄清单是唯一合法集合。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
src = io.open(STATE, encoding='utf-8').read()


def sub(old, new):
    global src
    assert src.count(old) == 1, (src.count(old), old[:70])
    src = src.replace(old, new)


# ── 1) §226 的测试搬到新变体 ─────────────────────────────────────────────────
sub('''            then: ChoiceThen::Copy,
            offered: Bounded::new(),
            copies: 2,
            candidates,
        };
        // ④ 先问自洽：`then = Exhaust` + `copies = 2` 是两个方向的错都拒。
        assert_eq!(
            s.begin_choice(PendingChoice { then: ChoiceThen::Exhaust, ..question }),
            Err(ChoiceError::CopiesNotApplicable)
        );
        assert_eq!(
            s.begin_choice(PendingChoice { copies: 0, ..question }),
            Err(ChoiceError::CopiesNotApplicable)
        );''',
    '''            then: ChoiceThen::Copy {
                copies: 2,
                into: CardZone::Hand,
            },
            offered: Bounded::new(),
            candidates,
        };
        // ④ "复制 0 份"仍要拒 —— 它是一次**成功**的空操作，那是最难发现的一种错。
        //   （§227 之后"副本数"长在变体里，所以"`then = Exhaust` 却带 copies"已经构造不出来。）
        assert_eq!(
            s.begin_choice(PendingChoice {
                then: ChoiceThen::Copy {
                    copies: 0,
                    into: CardZone::Hand,
                },
                ..question
            }),
            Err(ChoiceError::CopiesNotApplicable)
        );''')

sub('''        assert_eq!(
            s.pending_choice().map(|choice| choice.copies),
            Some(2),
            "a refusal keeps the question open"
        );''',
    '''        assert_eq!(
            s.pending_choice().map(|choice| choice.then),
            Some(ChoiceThen::Copy {
                copies: 2,
                into: CardZone::Hand,
            }),
            "a refusal keeps the question open"
        );''')

# ── 2) 两个新变体的判据（插在 §226 那条之后） ─────────────────────────────────
anchor = '''    #[test]
    fn an_offered_choice_and_a_pile_choice_cannot_answer_each_other() {'''
assert src.count(anchor) == 1
tests = '''    /// §227：`Upgrade` —— 选中的牌**原地**升级（定义 id 变 `<id>+`），牌不搬。
    ///
    /// 三件事：升级真的发生、牌还在原处、而"已经带 `+` 的牌"再升级是**响亮拒绝**
    /// （`NotUpgradable`，不是"什么都不做"）—— 后者是内核能看见的那一半规则，
    /// 另一半（有没有 `+` 行）由发问的节点收窄候选。
    #[test]
    fn an_upgrade_choice_rewrites_the_definition_in_place() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.create_card_instance(&cid("hero"), cdid("standard.strike"), CardZone::Hand)
            .expect("the pool has room");
        let ids = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::Upgrade,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .expect("the question is answerable");

        let done = s
            .resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0)
            .expect("upgraded");
        assert_eq!(done.picked, 1);
        // 牌还在手牌里的**同一个位置**（`Upgrade` 不搬牌）。
        assert_eq!(pile_ids(&s, CardZone::Hand), ids, "the card did not move");
        let definition = s
            .card(s.find_card(&cid("hero"), &ids[0]).expect("still there").1)
            .expect("the card")
            .definition_id;
        assert_eq!(definition.as_str(), "standard.strike+");

        // 再升级一次 ⇒ **响亮拒绝**（`+` 只能加一次）。
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::Upgrade,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .expect("the question is answerable");
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0),
            Err(ChoiceError::NotUpgradable)
        );
        assert!(s.pending_choice().is_some(), "a refusal keeps the question open");
    }

    /// §227：`ToDrawPileTop` —— 选中的牌搬到抽牌堆**顶**（`ZonePlacement::Top` = 下一张就抽它）。
    ///
    /// 判据必须比"它在抽牌堆里"更强：先往抽牌堆放一张垫底的牌，然后问"谁在最前面"。
    #[test]
    fn a_to_draw_pile_top_choice_lands_on_the_draw_top() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.create_card_instance(&cid("hero"), cdid("standard.strike"), CardZone::Hand)
            .expect("the pool has room");
        // 垫底：`standard.defend` 先进抽牌堆，所以它**不该**是下一张。
        s.create_card_instance(&cid("hero"), cdid("standard.defend"), CardZone::DrawPile)
            .expect("the pool has room");
        let ids = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::ToDrawPileTop,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .expect("the question is answerable");
        s.resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0)
            .expect("moved");

        assert!(pile_ids(&s, CardZone::Hand).is_empty(), "it left the hand");
        let draw = pile_ids(&s, CardZone::DrawPile);
        assert_eq!(draw.len(), 2, "two cards in the draw pile, got {draw:?}");
        assert_eq!(
            draw[0], ids[0],
            "the picked card is on **top** (index 0 is the draw top), got {draw:?}"
        );
    }

''' + anchor
src = src.replace(anchor, tests)
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)
print('ok state tests')
