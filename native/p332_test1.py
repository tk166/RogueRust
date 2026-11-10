"""§332：既有商店判据要跟上 wiki 的新规则。

两处：

1. `a_shop_stocks_five_cards_and_three_relics_with_prices_in_range` —— 五张卡里**恰好一张
   5 折**（wiki: *"One random card will have a 50% discount applied"*），所以"每张都在
   45-55"不再成立：那一张是 `low/2 ..= high/2`。判据改成"**恰好一张**在半价带、其余在原价带"。
2. 遗物价目从"一律 143-157"变成**按稀有度**（`relic_price_band`），所以那条断言改用同一个函数。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """        for offer in run.shop().cards() {
            // All five are Commons, so they sit in the Common band (`inv:§8.2`) -- no more
            // `[推断]`: the band now comes from the card's rarity.
            let (low, high) = card_price_band(Rarity::Common);
            assert!(
                (low..=high).contains(&offer.price),
                "card {} costs {}",
                offer.id.as_str(),
                offer.price
            );
            assert!(common_pool().iter().any(|card| card.id == offer.id.as_str()));
        }
        for offer in run.shop().relics() {
            assert!((143..=157).contains(&offer.price), "relic price {}", offer.price);
        }""",
        """        // §332：wiki 的 *"One random card will have a 50% discount applied"* —— 于是**恰好一张**
        // 落在半价带、其余落在原价带。只测"都在原价带"会让"没有打折"也绿（§332 之前就是那样）。
        let (low, high) = card_price_band(Rarity::Common);
        let mut discounted = 0usize;
        for offer in run.shop().cards() {
            let full = (low..=high).contains(&offer.price);
            let half = (low / 2..=high / 2).contains(&offer.price);
            assert!(
                full || half,
                "card {} costs {} (neither the {low}-{high} band nor its half)",
                offer.id.as_str(),
                offer.price
            );
            if half {
                discounted += 1;
            }
            assert!(common_pool().iter().any(|card| card.id == offer.id.as_str()));
        }
        assert_eq!(discounted, 1, "exactly one card is on sale");
        for offer in run.shop().relics() {
            // §332：遗物价目按**稀有度**（`relic_price_band`），不再一律 143-157。
            let rarity = RELICS
                .iter()
                .find(|entry| entry.id == offer.id.as_str())
                .map_or(Rarity::Common, |entry| entry.rarity);
            let (low, high) = relic_price_band(rarity);
            assert!(
                (low..=high).contains(&offer.price),
                "relic {} costs {} (band {low}-{high})",
                offer.id.as_str(),
                offer.price
            );
        }""",
        'shop price test')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('shop test updated')
