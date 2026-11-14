"""§377 的测试：商店有色卡的稀有度档位（9/37/54）。

三条判据：
1. **边界**：`shop_bands` 在保底 0 / −5 / +10 两侧的值（含"被裁掉的部分进 Common"）；
2. **不更新保底**：连开 20 家店，`rarity_offset` 一个字节都不动（wiki：Shop 的 roll 只**受**
   保底影响，不**更新**它）；
3. **实际分布**：开 400 家店统计 2000 个货位，Rare 的比例要落在 9% 附近（宽区间，不是精确值 ——
   随机流不该被钉死），并且**明显低于**"按池子占比均匀抽"会得到的那个数。
   ⚠️ 第 3 条是真正抓住"稀有度没掷"的那一条：只断言档位函数的话，`stock_shop` 里
   不调用它也照样绿（§4.19：守卫装在了切口下游）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''    /// §342（第九轮 Review P1-2）：补出来的遗物按**它自己的稀有度**定价。'''
assert t.count(ANCHOR) == 1

BLOCK = '''    /// §377：商店有色卡的档位边界 —— wiki 的 9/37/54，且**受**保底影响、**不更新**保底。
    ///
    /// 为什么把边界单独立一条：玩家报的是"第一次进商店就能低价买到残杀（Rare）"，
    /// 而根因是"稀有度**根本没掷**"。边界函数对了但没人调用它，故障照旧 —— 所以
    /// `shop_stocks_colored_cards_by_rarity_odds` 那条统计测试才是真正的守卫。
    #[test]
    fn shop_rarity_bands_match_the_wiki() {
        // 保底 0：稀有 0..9、Uncommon 9..46、Common 46..100 ⇒ 9 / 37 / 54。
        assert_eq!(shop_bands(0), (9, 46), "at offset 0 the bands are 9 / 37 / 54");
        // 保底 −5（开局）：稀有 0..4，被裁掉的 5 个点进 **Common**（不是 Uncommon）⇒ 4 / 37 / 59。
        assert_eq!(shop_bands(-5), (4, 41), "a negative offset clips into Common, not Uncommon");
        // 保底 +10：稀有 0..19、Uncommon 19..56。
        assert_eq!(shop_bands(10), (19, 56));
        // 极端负保底：稀有档夹到 0，Uncommon 也整体下移（宽度不变）。
        assert_eq!(shop_bands(-20), (0, 17), "the rare band floors at 0 and uncommon slides down");

        // 三档宽度之和恒等于 100 —— 这是"一张 roll 分三段"的直接后果。
        for offset in -5..=20 {
            let (rare_top, uncommon_top) = shop_bands(offset);
            assert!(
                (0..=100).contains(&rare_top) && rare_top <= uncommon_top && uncommon_top <= 100,
                "offset {offset}: bands must stay ordered inside 0..=100"
            );
        }
    }

    /// §377：**商店的 roll 不更新稀有度保底**（wiki："Shop Cards … do not affect rare offset,
    /// however they are affected by rare chance"）。
    ///
    /// 判据：连开 20 家店，`rarity_offset` 一次都不许动。写成"至少一个字节不变"就够 ——
    /// 但这里要的是**每一家店之后都等于开局值**，因为"+1 一次"正是最容易漏的那一半。
    #[test]
    fn stocking_a_shop_does_not_move_the_rare_offset() {
        let mut run = ironclad();
        run.pending = Pending::Shop;
        let start = run.rarity_offset;
        assert_eq!(start, RARITY_OFFSET_START, "a fresh run starts at the wiki's −5%");
        for round in 0..20 {
            run.stock_shop(&TYPED_CARDS, &RELICS, &POTIONS).expect("stock the shop");
            assert_eq!(
                run.rarity_offset, start,
                "round {round}: shops must not tick (or reset) the rare pity offset"
            );
        }
    }

    /// §377：**稀有度真的掷了**（这才是玩家那条报障的守卫）。
    ///
    /// 夹具：一个只有 **3 张 Common / 1 张 Uncommon / 1 张 Rare** 的攻击牌池。
    /// 如果实现是"在类型组里均匀抽"（旧形状），Rare 的占比会是 **20%**；
    /// 按 wiki 的 9% 掷，Rare 应该落在 5%–14% 之间（400 家店 × 2 个攻击位 = 800 个样本，
    /// 二项分布的 4σ 约 ±4%）。
    ///
    /// ⚠️ 区间是**故意**宽的：断言"恰好 9.0%"会让随机流的任何一次调整都变红。要证明的是
    /// "**它被掷了**"，不是"这个数是 9"——后者由上面那条边界测试守。
    #[test]
    fn shop_stocks_colored_cards_by_rarity_odds() {
        let pool: [PoolCard<'static>; 5] = [
            PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "twin_strike", rarity: Rarity::Uncommon, kind: CardKind::Attack, upgraded: None, colorless: false },
            PoolCard { id: "bludgeon", rarity: Rarity::Rare, kind: CardKind::Attack, upgraded: None, colorless: false },
        ];
        let mut run = ironclad();
        run.pending = Pending::Shop;
        let mut rare = 0usize;
        let mut uncommon = 0usize;
        let mut common = 0usize;
        for _ in 0..400 {
            run.stock_shop(&pool, &RELICS, &POTIONS).expect("stock the shop");
            for offer in run.shop().cards() {
                match offer.id.as_str() {
                    "bludgeon" => rare += 1,
                    "twin_strike" => uncommon += 1,
                    _ => common += 1,
                }
            }
        }
        let total = rare + uncommon + common;
        assert!(total > 500, "the fixture must shelve plenty of cards (got {total})");
        let rare_percent = rare * 100 / total;
        assert!(
            (5..=14).contains(&rare_percent),
            "Rare must be rolled at the wiki's 9%, not uniform-by-pool-share (20%). \\
             Got {rare_percent}% ({rare}/{total}) — if this is ~20%, the rarity roll is missing"
        );
        assert!(
            uncommon > 0 && common > 0,
            "every band must be reachable (common {common}, uncommon {uncommon}, rare {rare})"
        );
    }

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('§377 tests added')
