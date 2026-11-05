"""§220 tests: the two new lifecycle carriers, driven through real fights."""
import io

H = 'kernel/rd-core/src/host.rs'
INV = 'native/card_wiki_inventory.py'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(H, '''    /// §219：`Exhaust` 是**落区**，而且要真的能用''',
    '''    /// §220：`LifecyclePrograms[Drawn]` —— wiki 的 "Whenever this card is drawn, lose 1 Energy."
    ///
    /// `Drawn` 与 `Exhausted` 是**内核新加的两个生命周期事件**（参考的 `CardLifecycleTrigger`
    /// 只有 `TurnEndInHand`）。它们在 `state.move_card` 这个**唯一的落区漏斗**上发请求：
    /// 抽牌堆→手牌 = `Drawn`，任何区→消耗堆 = `Exhausted`。选择在那个漏斗上发，是因为另一条路
    /// 要在"回合开始的抽牌、`drawCards` 节点、药水、弃牌堆洗回"每一处各写一遍，漏一处就是静默少跑。
    ///
    /// 判据走真实状态机：**把手牌抽起来**（`draw_card`，不是直接摆牌），能量必须 -1。
    #[test]
    fn a_void_drawn_from_the_pile_costs_one_energy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // 抽牌堆顶端放一张 Void（`draw_card` 抽的是**队首**）。
        give_card(&mut state, &content, "hero", CardZone::DrawPile, "void");
        assert_eq!(energy_of(&state, "hero"), 3);

        let slot = state.draw_card(&cid("hero")).expect("draw").expect("a card");
        // 抽牌本身把牌放进手牌；`Drawn` 节目是**入队**的，排空才生效。
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "the void is in hand"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "wiki: \\"Whenever this card is drawn, lose 1 Energy.\\" (slot {})\\", slot.0
        );
    }

    /// §220：`LifecyclePrograms[Exhausted]` —— wiki 的 "If this card is Exhausted, gain 2 Energy."
    ///
    /// 消耗的入口不止"打出即消耗"：虚无（回合末）、内容里的 `moveCardToZone` 都算。所以判据用
    /// **回合末的虚无清理**这条真实路径，而不是手动把牌塞进消耗堆。
    #[test]
    fn a_sentinel_that_gets_exhausted_pays_two_energy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        // `sentinel+` 是 3 点能量（节目挂在**定义**上，所以升级行有自己的一份）。
        for (card_id, expected) in [("sentinel", 2), ("sentinel+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_card(&mut state, &content, "hero", CardZone::Hand, card_id);
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            let before = energy_of(&state, "hero");
            // 回合末：`ethereal` 把它送进消耗堆 ⇒ `move_card` 发 `Exhausted` ⇒ 节目给能量。
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            assert_eq!(
                zone_count(&state, "hero", CardZone::ExhaustPile),
                1,
                "{card_id}: ethereal moves it to the exhaust pile at turn end"
            );
            assert_eq!(
                energy_of(&state, "hero"),
                before + expected,
                "{card_id}: wiki says +{expected} Energy when exhausted"
            );
        }
    }

    /// §219：`Exhaust` 是**落区**，而且要真的能用''',
    'tests')

# §218 的两条偏差已经解决：void / sentinel 的说明要更新（不然矩阵里还声称"没载体"）
one(INV, """    'sentinel': {
        'why': 'wiki 没有 Ethereal（旧版有），内容带 `ethereal`；而 wiki 的报酬是"被 Exhaust 时给能量"，'
               '内容没有这条触发器（`ethereal` 会在回合末把它送进消耗堆，但没有任何东西读"被消耗"）。',
        'content_keywords': ['Ethereal'],
    },""",
    """    'sentinel': {
        'why': 'wiki 没有 Ethereal（旧版有），内容带 `ethereal`。§220 起"被 Exhaust 时给 2(3) 能量"'
               '**已经实现**（`LifecyclePrograms[Exhausted]`），所以这条偏差只剩 Ethereal 标签本身。',
        'content_keywords': ['Ethereal'],
    },""",
    'sentinel deviation')
