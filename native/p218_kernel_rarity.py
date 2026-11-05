"""§218 kernel: the run layer needs a `Special` card bucket (the wiki's "event-only" rarity).

Apparition's page says `Rarity = Special`. Without a bucket for it, `Rarity::from_name` returns `None`,
`full_pool()` refuses the whole card table, and **every** `rd_run_choose_start` fails with `-2`
(that is how this was found: 6 wasm run tests went red after the rarity fix, all pointing at
"taking blessing 0").

Same shape as §160's `Rarity::Event` for relics: the bucket exists so "event-only" is *sayable*, and it
is filtered out of every reward roll. The three filters that already skip `Status | Curse` must skip it
too, or Apparition becomes an ordinary uncommon reward.
"""
import io

P = 'kernel/rd-run/src/state.rs'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


one('''    Event = 6,
}''',
    '''    Event = 6,
    /// §218：wiki 把**事件专属**的卡牌放在 `Special` 桶里（`apparition`）。
    ///
    /// 与 `Event`（遗物）同一个道理：这个桶让"事件才有"成为**可说的**，而不是靠"谎报成 Uncommon"
    /// —— 谎报的后果是它进了普通奖励池（Apparition 是"获得 1 层无形"，不该每场奖励都能刷到）。
    /// 所有按稀有度抽牌的地方都要把它排除。
    Special = 7,
}''',
    'Special bucket')

one('''            "Event" => Some(Self::Event),
            _ => None,''',
    '''            "Event" => Some(Self::Event),
            // §218: the wiki's bucket for event-only cards (`apparition`).
            "Special" => Some(Self::Special),
            _ => None,''',
    'from_name')

# 抽牌的三处过滤：Status/Curse 之外还要跳过 Special。
one('''            if !matches!(pool[index].rarity, Rarity::Status | Rarity::Curse) {''',
    '''            if !matches!(
                pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {''',
    'grant_random_cards filter')

one('''            if !matches!(card_pool[index].rarity, Rarity::Status | Rarity::Curse) {''',
    '''            if !matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {''',
    'reward pool filter')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('run layer: Special bucket added')
