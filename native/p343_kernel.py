"""§343：删卡服务**每家店只能用一次**（wiki 两源明文）。

## 规则

wiki.gg · The Merchant：*"Card Removal Service — Can only be used **once per Shop**. Its price
starts at 75 Gold and increases by 25 each time it is bought at a shop."*
fandom · Merchant 同句。

两句话是**两件事**，我们原来只做对了一半：

* **价格**按 `removed_cards` 跨店累计 +25 —— 早就对了（§159）；
* **每家店一次**从来没有实现 ⇒ 现在能在同一家店里连删三张（75 → 100 → 125），而 StS 只给一次。

## 字段

`removed_this_shop: bool` —— 布尔而不是计数：一家店只允许一次，"现在几次"是个不存在的问题。
它在 `enter_shop` 里清，于是"换一家店又能删"是自动的。

⚠️ 与 `removed_cards` 的语义分工要写清：那个是**服务涨价**（跨店累计），这个是**本次访问的
次数上限**。混成一个字段会让"删一张牌之后价格涨了"和"这家店不能删了"变成同一个数。

## 为什么这条会牵动存档与指纹

新字段 = 新字节：`archive.rs` 的 payload 必须抬版本（11 → 12），`hash.rs` 必须把它写进指纹，
否则 §308 的 `state-fields` 闸门会红 —— 那道闸门正是为"加了字段忘了存/忘了算"设的。
`sample_full()` 也要显式设它，否则"漏还原一个字段就红"那句话又变成假的。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
STREAMS = 'kernel/rd-run/src/streams.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 错误变体 ──────────────────────────────────────────────────────────────
t = io.open(STREAMS, encoding='utf-8').read()
t = sub(t, '''    /// §189 `A10`：这张牌不能被删（Ascender's Bane："Cannot be removed"）。
    CannotRemove,''',
        '''    /// §189 `A10`：这张牌不能被删（Ascender's Bane："Cannot be removed"）。
    CannotRemove,
    /// §343：这家店的删卡服务**这一趟已经用过了**。
    ///
    /// 自己的变体而不是复用 `WrongPhase`：相位是对的（人就站在商店里），错的是**次数**。
    /// wiki.gg / fandom 都写 "Can only be used once per Shop"，而页面要说的话
    /// （"这家店删过了，换一家"）与"你不在商店里"完全不同。
    RemovalUsed,''', 'RemovalUsed')
io.open(STREAMS, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 字段 ──────────────────────────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()

t = sub(t, '''    removed_cards: i32,''',
        '''    /// 商店删卡服务的**计价步数**：每用一次 +1，价格 = 75 + 25 × 这个数（**跨店累计**）。
    removed_cards: i32,
    /// §343：**这家店**的删卡服务已经用过了。
    ///
    /// wiki.gg：*"Card Removal Service — Can only be used once per Shop."* 与 `removed_cards`
    /// 是**两件事**：那个是服务涨价（跨店累计），这个是**本次访问的次数上限**。合成一个字段
    /// 会让"删过之后价格涨了"与"这家店不能删了"变成同一个数。
    ///
    /// 在 `enter_shop` 里清 ⇒ "换一家店又能删"是自动的。
    removed_this_shop: bool,''', 'field')

# 初始化（`new_with_ascension` 的 struct literal）
t = sub(t, '''            removed_cards: 0,''', '''            removed_cards: 0,
            removed_this_shop: false,''', 'initializer')

# `enter_shop` 清位
t = sub(t, '''        self.stock_shop(card_pool, relic_pool, potion_pool)?;''',
        '''        self.stock_shop(card_pool, relic_pool, potion_pool)?;
        // §343：**新的一家店** ⇒ 删卡服务又能用一次。放在 `stock_shop` **之后**：铺货失败时
        // 这一趟店没开成，不该把上一家店的状态清掉。
        self.removed_this_shop = false;''', 'enter_shop clears')

# `remove_card` 检查 + 置位
t = sub(t, '''        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }''',
        '''        // §343：**一家店只能删一次**（wiki.gg / fandom 同一句）。检查放在价格之前：
        // 用过了就不该再谈价钱。
        if self.removed_this_shop {
            return Err(RunError::RemovalUsed);
        }
        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }''', 'remove_card check')

t = sub(t, '''        // §259：`removed_cards` 是**商店服务的计价步数**（+25/次），不是"删过几张牌" ——
        // 所以它留在这里，而不是搬进共用的 `remove_deck_card`（`Toke` 不该让商店涨价）。
        self.removed_cards += 1;
        Ok(price)''',
        '''        // §259：`removed_cards` 是**商店服务的计价步数**（+25/次），不是"删过几张牌" ——
        // 所以它留在这里，而不是搬进共用的 `remove_deck_card`（`Toke` 不该让商店涨价）。
        self.removed_cards += 1;
        // §343：这一家店的额度用掉了。
        self.removed_this_shop = true;
        Ok(price)''', 'remove_card sets')

# 访问器（放在 `remove_card_price` 前面，读者一眼能看到两者成对）
t = sub(t, '''    pub fn remove_card_price(&self) -> i32 {''',
        '''    /// §343：这家店的删卡服务**还能不能用**（wiki: "once per Shop"）。
    ///
    /// 页面拿它决定"删一张牌"那个按钮画不画得动。单独一个导出而不是让价格返回 `-1`：
    /// 价格那一格要显示"75 金"，把"不可用"塞进同一个数会让页面把 `-1` 印成价格。
    #[must_use]
    pub const fn removal_available(&self) -> bool {
        !self.removed_this_shop
    }

    pub fn remove_card_price(&self) -> i32 {''', 'accessor')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ 存档：抬版本 + 写 + 读 + 还原 ─────────────────────────────────────────
t = io.open(ARCHIVE, encoding='utf-8').read()
t = sub(t, '''const VERSION: u8 = 11;  // §308：事件链 + 宝箱计数器 + 每副本 mark。''',
        '''const VERSION: u8 = 12;  // §343：`removed_this_shop`。§308：事件链 + 宝箱计数器 + 每副本 mark。''',
        'version')

t = sub(t, '''    // §301：已经打过几场（`neows_lament` 的"前 3 场"就靠这个数）。
    writer.byte(state.fights())?;''',
        '''    // §301：已经打过几场（`neows_lament` 的"前 3 场"就靠这个数）。
    writer.byte(state.fights())?;
    // §343：这家店的删卡服务用掉没有（`false`/`true` → 0/1）。
    writer.byte(u8::from(state.removed_this_shop))?;''', 'write')

t = sub(t, '''    // §301
    let fights = reader.byte()?;''',
        '''    // §301
    let fights = reader.byte()?;
    // §343
    let removed_this_shop = reader.byte()?;''', 'read')

t = sub(t, '''    restored.fights = fights;''',
        '''    restored.fights = fights;
    restored.removed_this_shop = removed_this_shop != 0;''', 'restore')

# 让 `sample_full()` 真的设上它 —— 否则"漏还原一个字段就红"又变成假话。
t = sub(t, '''        // `A20` 的两场 Boss 进度。
        run.bosses_fought = 1;
        run''',
        '''        // `A20` 的两场 Boss 进度。
        run.bosses_fought = 1;
        // §343：这家店的删卡服务用掉了。**必须显式设**：留默认值 `false` 的话，
        // "漏还原一个字段就红"这句话对它就是假的（§308 的同一个教训）。
        run.removed_this_shop = true;
        run''', 'sample_full')
io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ 指纹 ──────────────────────────────────────────────────────────────────
t = io.open(HASH, encoding='utf-8').read()
t = sub(t, '''        .str("fights=")''',
        '''        // §343：这家店的删卡服务用掉没有。它是**可观察**的（"删一张牌"按钮灰了），
        // 而且它决定下一步的合法动作集 ⇒ 必须进指纹。
        .str("removal_used=")
        .u32(u32::from(state.removed_this_shop))
        .str("fights=")''', 'hash')
io.open(HASH, 'w', encoding='utf-8', newline='\n').write(t)
print('§343: RemovalUsed + removed_this_shop + archive v12 + hash')
