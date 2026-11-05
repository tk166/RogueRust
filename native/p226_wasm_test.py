"""§226 (part 8): rd-wasm 层的端到端判据 —— 页面拿到的三个数必须与内核一致。

内核测试证明"复制是对的"，这一条证明**页面读到的三个数也对**（`kind = 4`、`copies`、以及
`count` 用的是收窄后的清单）。缺它的话，"同一个词表被两处认识就一定漂"（§161.3 的形态）会在
`rd_env_choice_*` 这一层重现：页面说"选 1 张"，内核说"这张不在来源里"。
"""
import io

LIB = 'kernel/rd-wasm/src/lib.rs'

src = io.open(LIB, encoding='utf-8').read()

anchor = '''    /// §208：`StartingBlock` —— Jaw Worm 开局就带 6 格挡（A17: 9）。'''
assert src.count(anchor) == 1

test = '''    /// §226：`Dual Wield` 在 **run/页面层**的那三个数：`kind = 4`、`copies = 1`、`count = 收窄后`。
    ///
    /// 这条判据存在的理由很具体：`rd_env_choice_count` / `rd_env_choice_confirm` /
    /// `pile_card_id(3, i)` 原来各读一次**牌区**。收窄过的问句里合法选项比牌区少，三处只要有一处
    /// 忘了改，页面就会画出内核随后要拒绝的那一项 —— 而"点了没反应"正是最难从日志里认出来的形态。
    #[test]
    fn a_dual_wield_question_reads_the_same_three_numbers_in_the_page_layer() {
        let session = build_session_at(7, "enc_jaw_worm", 200, None, 0, 0)
            .expect("the jaw worm fight builds");
        install_session(session);
        let content = content();
        let hero = cid_in("hero");
        // 手牌：一张攻击（唯一合法答案）+ 一张技能（必须被过滤掉）+ 那张牌自己。
        let mut hand_index = None;
        {
            let session = slot().as_mut().expect("session");
            for (index, definition) in ["strike", "defend", "dual_wield"].iter().enumerate() {
                let definition = rd_core::state::CardDefinitionId::new(definition)
                    .expect("short definition id");
                session
                    .state
                    .create_card_instance(&hero, definition, rd_core::state::CardZone::Hand)
                    .expect("the hand has room");
                let _ = index;
            }
            session.reobserve();
            // §161.4: the step names a **hand position**, so find the position of `dual_wield`.
            hand_index = session.hand_zone().and_then(|zones| {
                (0..zones.count(rd_core::state::CardZone::Hand)).find(|index| {
                    zones
                        .slot_at(rd_core::state::CardZone::Hand, *index)
                        .and_then(|slot| session.state.card(slot))
                        .is_some_and(|card| card.definition_id.as_str() == "dual_wield")
                })
            });
        }
        let _ = &content;
        let hand_index = hand_index.expect("dual wield is in the hand");
        let verdict = rd_env_step(i32::try_from(hand_index).unwrap());
        assert_ne!(verdict, -3, "the play was refused: {}", session_error());
        assert_eq!(rd_env_choice_pending(), 1, "playing it asks a question");
        assert_eq!(rd_env_choice_kind(), 4, "4 = copy (the page writes the sentence from this)");
        assert_eq!(rd_env_choice_copies(), 1, "the printed card makes one copy");
        assert_eq!(
            rd_env_choice_count(),
            1,
            "only the Attack is a legal option -- the Skill and Dual Wield itself are not"
        );
        // 收窄后的选项**就是** strike（页面用 `pile_card_id(3, 0)` 画这张牌）。
        let option = pile_card_id(3, 0).expect("option 0 is readable");
        assert_eq!(option, "strike", "option 0 must be the Attack, got {option}");
        assert_eq!(rd_env_choice_pick(0, 1), 0);
        assert_eq!(rd_env_choice_confirm(), 0, "{}", session_error());
        assert_eq!(rd_env_choice_pending(), 0, "the question is answered");
        // 手牌：`strike` 两份 + `defend` 一份（`dual_wield` 打完就走了）。
        let hand: Vec<String> = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .map(|card| card.definition_id.as_str().to_string())
                .collect()
        };
        assert_eq!(
            hand.iter().filter(|id| id.as_str() == "strike").count(),
            2,
            "the copy landed in the hand: {hand:?}"
        );
        assert!(hand.iter().any(|id| id == "defend"), "{hand:?}");
        assert!(!hand.iter().any(|id| id == "dual_wield"), "{hand:?}");
        take_session();
    }

''' + anchor

src = src.replace(anchor, test)
io.open(LIB, 'w', encoding='utf-8', newline='\n').write(src)
print('ok wasm test')
