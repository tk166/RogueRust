"""§332 修：`Rng::shuffle` 的入参是**位置表**，不是值表。

`rng::shuffle_indexes` 的第一件事是 `out[i] = i`（它洗的是"位置"），所以往里塞"选中的池下标"
会被**重写**成 `0..len`。于是我的分类货架变成了"池子的前 N 张"，而补位那一遍又把已经在货架上的
牌加了一遍 ⇒ 同一张牌出现两次（`the_courier_restocks_the_slot_it_sells` 报
`the shelf must not shrink`，调试打印里 `bash` / `anger` 各两份）。

修法：洗一张 `pos = [0..found)` 的位置表，再用它去索引 `members` / `rest`。
**不要**去改 `shuffle_indexes`（它的语义是"位置"，改它等于改所有调用方）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# 分类那一遍：洗位置表
t = sub(t, """            self.rng.shuffle(RunStream::Shop, &mut members[..found]);
            std::eprintln!("DEBUG bucket {:?} found={} members={:?} pool={:?}", kind, found, &members[..found],
                card_pool.iter().map(|c| (c.id, c.kind)).collect::<Vec<_>>());
            for slot in 0..count.min(found) {
                let card = card_pool[members[slot] as usize];""",
        """            // ⚠️ `shuffle` 洗的是**位置表**（它先把切片写成 `0..n`），所以这里洗 `pos` 而不是
            // `members` —— 直接洗 `members` 会把它重写成"池子的前 N 张"（§332 踩过）。
            let mut pos = [0u8; MAX_POOL];
            for (slot, entry) in pos.iter_mut().take(found).enumerate() {
                *entry = slot as u8;
            }
            self.rng.shuffle(RunStream::Shop, &mut pos[..found]);
            for slot in 0..count.min(found) {
                let card = card_pool[members[pos[slot] as usize] as usize];""",
        'bucket shuffle')

# 补位那一遍：同一处修正
t = sub(t, """            self.rng.shuffle(RunStream::Shop, &mut rest[..found]);
            for slot in 0..found {
                if shelved_cards == MAX_SHOP_CARDS {
                    break;
                }
                let card = card_pool[rest[slot] as usize];""",
        """            let mut pos = [0u8; MAX_POOL];
            for (slot, entry) in pos.iter_mut().take(found).enumerate() {
                *entry = slot as u8;
            }
            self.rng.shuffle(RunStream::Shop, &mut pos[..found]);
            for slot in 0..found {
                if shelved_cards == MAX_SHOP_CARDS {
                    break;
                }
                let card = card_pool[rest[pos[slot] as usize] as usize];""",
        'fill-up shuffle')

# 拆掉测试里的调试打印
t = sub(t, """        std::eprintln!("DEBUG shelf={:?}", run.shop().cards().iter().map(|o| (o.id.as_str(), o.price)).collect::<Vec<_>>());
""", "", 'debug print')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('shuffle misuse fixed')
