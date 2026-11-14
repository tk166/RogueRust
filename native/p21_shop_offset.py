"""§377 补丁 4：统计测试要把**保底**这一层也分开测。

第一次跑出 3%（= 79/2000），不是"没掷"，而是**开局保底是 −5%** ⇒ 商店的稀有档 = 9 − 5 = 4%。
wiki 的原话是商店的 roll *受*稀有度保底影响（"Shop Cards … are affected by rare chance"），
所以 4% 是**对的**。测试因此要分两段：

* 保底 0（把 `rarity_offset` 摆到 0）⇒ Rare ≈ **9%**（wiki 的基数）；
* 保底 −5（开局默认）⇒ Rare ≈ **4%**（基数 −5）—— 这一段同时证明"保底真的接进来了"。

只测第一段的话，"忘了读 `rarity_offset`"的实现会绿；只测第二段的话，"没掷档位"会绿。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''        let mut run = ironclad();
        run.pending = Pending::Shop;
        let mut rare = 0usize;
        let mut uncommon = 0usize;
        let mut common = 0usize;
        for _ in 0..400 {
            run.stock_shop(&pool, &RELICS, &POTIONS).expect("stock the shop");'''

NEW = '''        let mut run = ironclad();
        run.pending = Pending::Shop;
        // 第一段：把保底摆到 **0**，量到的就是 wiki 的基数 9%。
        run.rarity_offset = 0;
        let mut rare = 0usize;
        let mut uncommon = 0usize;
        let mut common = 0usize;
        for _ in 0..400 {
            run.stock_shop(&pool, &RELICS, &POTIONS).expect("stock the shop");'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD2 = '''        assert!(
            uncommon > 0 && common > 0,
            "every band must be reachable (common {common}, uncommon {uncommon}, rare {rare})"
        );
    }'''

NEW2 = '''        assert!(
            uncommon > 0 && common > 0,
            "every band must be reachable (common {common}, uncommon {uncommon}, rare {rare})"
        );

        // 第二段：**开局保底 −5%** ⇒ 商店的稀有档 = 9 − 5 = 4%（wiki："are affected by rare
        // chance"）。这一段证明保底真的接进了商店的 roll —— 少了它，"忘了读 `rarity_offset`"
        // 的实现照样绿（它只是把第一段的 9% 又跑一遍）。
        let mut fresh = ironclad();
        fresh.pending = Pending::Shop;
        assert_eq!(fresh.rarity_offset, RARITY_OFFSET_START, "a fresh run is at −5%");
        let mut fresh_rare = 0usize;
        let mut fresh_total = 0usize;
        for _ in 0..400 {
            fresh.stock_shop(&pool, &RELICS, &POTIONS).expect("stock the shop");
            for offer in fresh.shop().cards() {
                fresh_total += 1;
                if pool
                    .iter()
                    .any(|entry| entry.id == offer.id.as_str() && entry.rarity == Rarity::Rare)
                {
                    fresh_rare += 1;
                }
            }
        }
        let fresh_percent = fresh_rare * 100 / fresh_total;
        assert!(
            (2..=7).contains(&fresh_percent),
            "with the opening −5% pity the shop's rare band is 4%, not 9%. \\
             Got {fresh_percent}% ({fresh_rare}/{fresh_total}) — if this is ~9%, the offset is ignored"
        );
    }'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('两段：9%（保底 0）+ 4%（保底 −5）')
