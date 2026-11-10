"""§332 判据：一店**四排齐全**（wiki 的构成 + 价目）。

只测"某排有东西"是不够的：这次要钉的是**构成**（2/2/1、1+1、3、最右 Shop）与**价目**
（无色贵 20%、药水三档、遗物按稀有度）。所以用一份**按 wiki 构造**的小池子，逐排断言。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'

ANCHOR = """    #[test]
    fn a_shop_stocks_five_cards_and_three_relics_with_prices_in_range() {"""

TESTS = '''    /// §332：商店的四排**构成**与**价目**（wiki `The_Merchant`）。
    ///
    /// 一份按 wiki 构造的小池子：2 攻 / 2 技 / 1 能力的有色牌、1 张 Uncommon + 1 张 Rare 的无色牌、
    /// 三档药水、四档遗物。断言：
    ///
    /// * 有色 5 张，且**恰好** 2 攻 / 2 技 / 1 能力（分类是构成，不是随机）；
    /// * 无色 2 张 = 1 Uncommon + 1 Rare，价目落在 `colorless_price_band`（贵 20%）；
    /// * 药水 3 瓶，价目落在 `potion_price_band`，且**互不相同**；
    /// * 遗物 3 件，**最右那件是 `Shop` 档**，价目按稀有度（原来一律 143-157 是错的）。
    #[test]
    fn a_shop_stocks_all_four_shelves_with_the_wikis_composition() {
        const POOL: [PoolCard<'static>; 7] = [
            PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack,
                       upgraded: None, colorless: false },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack,
                       upgraded: None, colorless: false },
            PoolCard { id: "defend", rarity: Rarity::Common, kind: CardKind::Skill,
                       upgraded: None, colorless: false },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill,
                       upgraded: None, colorless: false },
            PoolCard { id: "demon_form", rarity: Rarity::Rare, kind: CardKind::Power,
                       upgraded: None, colorless: false },
            PoolCard { id: "bandage_up", rarity: Rarity::Uncommon, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
            PoolCard { id: "apotheosis", rarity: Rarity::Rare, kind: CardKind::Skill,
                       upgraded: None, colorless: true },
        ];
        const RELIC_POOL: [PoolRelic<'static>; 4] = [
            PoolRelic { id: "anchor", rarity: Rarity::Common },
            PoolRelic { id: "pen_nib", rarity: Rarity::Uncommon },
            PoolRelic { id: "runic_pyramid", rarity: Rarity::Rare },
            PoolRelic { id: "cauldron", rarity: Rarity::Shop },
        ];
        const POTION_POOL: [PoolPotion<'static>; 3] = [
            PoolPotion { id: "fire_potion", rarity: Rarity::Common },
            PoolPotion { id: "block_potion", rarity: Rarity::Common },
            PoolPotion { id: "energy_potion", rarity: Rarity::Uncommon },
        ];
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no merchant");
        assert_eq!(
            run.begin_node_stocked(&POOL, &RELIC_POOL, &POTION_POOL),
            Ok(NodeKind::Shop)
        );

        // ── 有色卡：5 张，2 攻 / 2 技 / 1 能力 ──────────────────────────────────
        let cards = run.shop().cards();
        assert_eq!(cards.len(), MAX_SHOP_CARDS);
        let mut attacks = 0usize;
        let mut skills = 0usize;
        let mut powers = 0usize;
        for offer in cards {
            let kind = POOL
                .iter()
                .find(|card| card.id == offer.id.as_str())
                .map(|card| card.kind)
                .expect("the offer came from the pool");
            assert!(
                !POOL
                    .iter()
                    .find(|card| card.id == offer.id.as_str())
                    .expect("from the pool")
                    .colorless,
                "a colorless card must not sit on the colored shelf"
            );
            match kind {
                CardKind::Attack => attacks += 1,
                CardKind::Skill => skills += 1,
                CardKind::Power => powers += 1,
                CardKind::Unknown => panic!("unknown kind on the shelf"),
            }
        }
        assert_eq!((attacks, skills, powers), (2, 2, 1), "wiki: 2 attacks, 2 skills, 1 power");

        // ── 无色货架：1 Uncommon + 1 Rare，价目贵 20% ──────────────────────────
        let colorless = run.shop().colorless();
        assert_eq!(colorless.len(), MAX_SHOP_COLORLESS);
        let mut rarities: Vec<Rarity> = colorless
            .iter()
            .map(|offer| {
                POOL.iter()
                    .find(|card| card.id == offer.id.as_str())
                    .expect("from the pool")
                    .rarity
            })
            .collect();
        rarities.sort_by_key(|rarity| *rarity as u8);
        assert_eq!(rarities, vec![Rarity::Uncommon, Rarity::Rare], "one of each");
        for offer in colorless {
            let rarity = POOL
                .iter()
                .find(|card| card.id == offer.id.as_str())
                .expect("from the pool")
                .rarity;
            let (low, high) = colorless_price_band(rarity);
            assert!(
                (low..=high).contains(&offer.price),
                "colorless {} costs {} (band {low}-{high})",
                offer.id.as_str(),
                offer.price
            );
        }

        // ── 药水货架：3 瓶，价目按档，互不相同 ──────────────────────────────────
        let potions = run.shop().potions();
        assert_eq!(potions.len(), MAX_SHOP_POTIONS);
        let mut seen: Vec<&str> = Vec::new();
        for offer in potions {
            assert!(!seen.contains(&offer.id.as_str()), "no duplicate potion");
            seen.push(offer.id.as_str());
            let rarity = POTION_POOL
                .iter()
                .find(|entry| entry.id == offer.id.as_str())
                .map_or(Rarity::Common, |entry| entry.rarity);
            let (low, high) = potion_price_band(rarity);
            assert!(
                (low..=high).contains(&offer.price),
                "potion {} costs {} (band {low}-{high})",
                offer.id.as_str(),
                offer.price
            );
        }

        // ── 遗物货架：3 件，**最右那件是 `Shop` 档**，价目按稀有度 ────────────────
        let relics = run.shop().relics();
        assert_eq!(relics.len(), MAX_SHOP_RELICS);
        let last = relics.last().expect("three relics");
        let last_rarity = RELIC_POOL
            .iter()
            .find(|entry| entry.id == last.id.as_str())
            .expect("from the pool")
            .rarity;
        assert_eq!(
            last_rarity,
            Rarity::Shop,
            "wiki: the rightmost slot is always a Shop relic (got {:?})",
            last.id.as_str()
        );
        for offer in relics {
            let rarity = RELIC_POOL
                .iter()
                .find(|entry| entry.id == offer.id.as_str())
                .expect("from the pool")
                .rarity;
            let (low, high) = relic_price_band(rarity);
            assert!(
                (low..=high).contains(&offer.price),
                "relic {} ({rarity:?}) costs {} (band {low}-{high})",
                offer.id.as_str(),
                offer.price
            );
        }
    }

    #[test]
    fn a_shop_stocks_five_cards_and_three_relics_with_prices_in_range() {'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn a_shop_stocks_all_four_shelves_with_the_wikis_composition' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('four-shelf test inserted')
