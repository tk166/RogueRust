"""§226 (part 7): 两条判据。

① `state.rs`：`Copy` 的语义本身（原件不动、副本进手牌、收窄清单是唯一合法集合、
   `copies` 与 `then` 必须自洽）。
② `host.rs`：**端到端** —— 真的打一张 `Dual Wield`：问句出现、清单里**没有**技能牌、
   回答之后手牌多出一张同样的牌、Dual Wield 自己进消耗堆。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
HOST = 'kernel/rd-core/src/host.rs'

# ── ① state.rs ───────────────────────────────────────────────────────────────
src = io.open(STATE, encoding='utf-8').read()
anchor = '''    #[test]
    fn an_offered_choice_and_a_pile_choice_cannot_answer_each_other() {'''
assert src.count(anchor) == 1
test = '''    /// §226：`Copy` —— **原件不动、副本进手牌**，而收窄清单是唯一的合法集合。
    ///
    /// 四件事各一条断言，因为它们各自能单独坏掉：
    /// ① 清单外的牌不能答这个问句（页面根本不会列它，绕过页面也不能成）；
    /// ② 拒绝**一个字节都不改**（§161.2(a) 的老规矩）；
    /// ③ 造出 `copies` 份**同定义**的副本，原件仍在原处；
    /// ④ `copies` 与 `then` 不自洽时 `begin_choice` 当场拒绝（"复制 0 份"是一次成功的空操作）。
    #[test]
    fn a_copy_question_leaves_the_original_alone() {
        let mut s = hand_of(2);
        let ids = pile_ids(&s, CardZone::Hand);
        let mut candidates = Bounded::new();
        candidates
            .push(ids[0], Container::ChoiceOptions)
            .expect("one candidate fits");
        let question = PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::Copy,
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
        );
        s.begin_choice(question).expect("the question is answerable");

        // ① 清单说"只有第一张"，枚举就只能枚举出第一张。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Ok(1));
        assert_eq!(buf[0], ids[0]);

        // ② 清单外的牌被拒，而且状态一个字节都没变（整结构体相等）。
        let before = s;
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&ids[1..2]), 0),
            Err(ChoiceError::NotInSource)
        );
        assert!(s == before, "a refused answer must change nothing");

        // ③ 原件不动 + 两份副本进手牌（同一个定义 id）。
        let original = s.card(s.find_card(&cid("hero"), &ids[0]).expect("it is there").1)
            .expect("the card")
            .definition_id;
        let done = s.resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0).expect("copied");
        assert_eq!(done.picked, 2, "two copies were created");
        assert_eq!(s.pending_choice(), None, "the question is gone");
        let hand = pile_ids(&s, CardZone::Hand);
        assert_eq!(hand.len(), 4, "2 originals + 2 copies, got {hand:?}");
        assert!(
            hand.contains(&ids[0]),
            "the picked card itself must stay in the hand"
        );
        let mut copies = 0;
        for id in &hand {
            let slot = s.find_card(&cid("hero"), id).expect("in hand").1;
            if s.card(slot).expect("card").definition_id == original
                && *id != ids[0]
                && *id != ids[1]
            {
                copies += 1;
            }
        }
        assert_eq!(copies, 2, "both new instances carry the picked definition");
    }

''' + anchor
src = src.replace(anchor, test)
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)

# ── ② host.rs：端到端 ────────────────────────────────────────────────────────
src = io.open(HOST, encoding='utf-8').read()
anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1
test = '''    /// §226：`Dual Wield` —— **问玩家要一张 Attack 或 Power 牌，然后复制它**。
    ///
    /// 这是"复制载体"的端到端判据，一次钉住四段，缺一段就会出现"按钮是死的"那种失败：
    /// ① 打出之后**真的**有一个待决问句（`then = Copy`、`copies = 1`）；
    /// ② 选项是**收窄**过的：手里有攻击牌也有技能牌，问句只列攻击牌（`RequireAnyTag`）；
    /// ③ 回答之后手牌多一张**同定义**的牌，原件还在；
    /// ④ `Dual Wield` 自己按 `PlayedCardDestinationZone` 进消耗堆（wiki 的 `Exhaust`）。
    #[test]
    fn dual_wield_asks_for_an_attack_and_copies_it() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "dual_wield");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dual wield is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // ① 一个问题，`s then = Copy`、`copies = 1`、`min = max = 1`。
        let choice = state.pending_choice().expect("dual wield asks a question");
        assert!(choice.then == ChoiceThen::Copy, "then = {:?}", choice.then);
        assert_eq!(choice.copies, 1, "the printed card makes one copy");
        assert_eq!((choice.min, choice.max), (1, 1), "exactly one card");

        // ② 收窄：技能牌**不在**选项里（"choose an **Attack or Power** card"）。
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("the options are listable");
        assert_eq!(count, 1, "only the Attack qualifies, got {count}");
        let picked = legal[0];
        let picked_definition = state
            .card(state.find_card(&cid("hero"), &picked).expect("in hand").1)
            .expect("the card")
            .definition_id;
        assert_eq!(picked_definition.as_str(), "strike", "the Attack is the only option");

        // ③ 回答 ⇒ 手牌多一张同样的牌，原件还在。
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[picked]), 0)
            .expect("the answer is taken");
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(
            hand.iter().filter(|id| id.as_str() == "strike").count(),
            2,
            "the strike and its copy, got {hand:?}"
        );
        assert!(hand.iter().any(|id| id.as_str() == "defend"), "the Skill is untouched");
        assert!(!hand.iter().any(|id| id.as_str() == "dual_wield"), "{hand:?}");

        // ④ 它自己进消耗堆（wiki 的 `Exhaust`）。
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(
            exhausted.iter().any(|id| id.as_str() == "dual_wield"),
            "dual wield exhausts itself, got {exhausted:?}"
        );
    }

''' + anchor
src = src.replace(anchor, test)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok tests')
