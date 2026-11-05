"""§218 tests #2: `Special` cards are never rewarded, and `blur` really gives its Block."""
import io

S = 'kernel/rd-run/src/state.rs'
H = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(S, '''    /// **一条超长的内容池必须响亮失败，不许被截成 64**（REVIEW P1，§161.1）。''',
    '''    /// §218：wiki 的 `Special` 桶（事件专属的牌，`apparition`）—— 名字要能解析，**而且不进奖励**。
    ///
    /// 两半都是实战出来的：把 `apparition` 的稀有度从 Uncommon 改成 Special 时，
    /// `Rarity::from_name("Special")` 返回 `None` �� `full_pool()` 拒掉整张牌表 ⇒ **每一个**
    /// `rd_run_choose_start` 都以 -2 失败（6 条 wasm 测试同时红，报的是"taking blessing 0"）。
    /// 所以"能解析"要单独钉一次，否则下次有人加桶忘了 `from_name`，症状会出现在离得很远的地方。
    #[test]
    fn a_special_card_is_known_and_never_put_in_a_reward() {
        assert_eq!(Rarity::from_name("Special"), Some(Rarity::Special));
        let pool = [
            PoolCard { id: "apparition", rarity: Rarity::Special },
            PoolCard { id: "anger", rarity: Rarity::Common },
            PoolCard { id: "blur", rarity: Rarity::Uncommon },
            PoolCard { id: "bash", rarity: Rarity::Basic },
        ];
        for seed in 0..40 {
            let mut run = RunState::new(seed, 80, 0, &DECK).expect("a run");
            run.roll_reward(&pool, &[], &[], FightKind::Normal).expect("a reward");
            let cards: Vec<&str> = run.reward().cards().iter().map(RunId::as_str).collect();
            assert!(
                !cards.contains(&"apparition"),
                "seed {seed}: an event-only card showed up as a reward: {cards:?}"
            );
        }
    }

    /// **一条超长的内容池必须响亮失败，不许被截成 64**（REVIEW P1，§161.1）。''',
    'special test')

one(H, '''    /// §197：`Barricade`（永久）与 `Blur`（只保一次）''',
    '''    /// §218（卡牌 wiki 对照抓到的真错）：`Blur` 一直**只给了状态、没给格挡**。
    ///
    /// wiki：*"Gain 5 (8) Block. Block is not removed at the start of your next turn."*
    /// 这条同时钉两件事：格挡数值（5 / 8），以及状态本身还在（否则"下回合不清格挡"就不成立）。
    #[test]
    fn blur_gives_five_or_eight_block_and_the_status() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        for (card_id, expected_block) in [("blur", 5), ("blur+", 8)] {
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .unwrap_or_else(|error| panic!("{card_id}: {error:?}"));
            assert_eq!(block_of(&state, "hero"), expected_block, "{card_id}: wiki's Block");
            assert_eq!(stacks_of(&state, "hero", "standard.blur"), 1,
                       "{card_id}: the status is what keeps the block next turn");
        }
    }

    /// §197：`Barricade`（永久）与 `Blur`（只保一次）''',
    'blur test')
