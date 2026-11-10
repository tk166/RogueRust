"""§332（续）：把无色货架与药水货架接进**存档**与**指纹**（`state-fields` 闸门要求）。

写法照卡/遗物那两排：`len` 字节 + 每格 `id`/`price`。读侧用同一个 `read_offers`。
"""

import io

ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


a = io.open(ARCHIVE, encoding='utf-8').read()

# 写侧
a = sub(a, """    writer.byte(state.shop.relics_len)?;
    for offer in &state.shop.relics {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }""",
        """    // §332：无色货架与药水货架（与上面两排同一形状）。
    writer.byte(state.shop.colorless_len)?;
    for offer in &state.shop.colorless {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }
    writer.byte(state.shop.potions_len)?;
    for offer in &state.shop.potions {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }
    writer.byte(state.shop.relics_len)?;
    for offer in &state.shop.relics {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }""",
        'archive write')

# 读侧
a = sub(a, """    let mut shop_relics = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_RELICS];""",
        """    // §332：无色货架与药水货架（顺序必须与写侧**逐字对应**）。
    let mut shop_colorless = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_COLORLESS];
    shop.colorless_len = read_offers(&mut reader, &mut shop_colorless)?;
    shop.colorless = shop_colorless;
    let mut shop_potions = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_POTIONS];
    shop.potions_len = read_offers(&mut reader, &mut shop_potions)?;
    shop.potions = shop_potions;
    let mut shop_relics = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_RELICS];""",
        'archive read')
io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(a)
print('archive ok')

# 指纹：`state.shop` 的哪几排进哈希？先看现有写法。
h = io.open(HASH, encoding='utf-8').read()
if 'shop.cards' in h:
    print('hash already hashes shop shelves')
else:
    print('hash does NOT hash shop shelves yet — adding')
    h = sub(h, """    writer.str("event_relics=");""",
            """    // §332：商店四排（价格也是事实：打折/加价都改"以后会怎样"）。
    for (label, offers) in [
        ("shop_cards", state.shop.cards()),
        ("shop_colorless", state.shop.colorless()),
        ("shop_potions", state.shop.potions()),
        ("shop_relics", state.shop.relics()),
    ] {
        writer.str(label).str("=");
        for offer in offers {
            writer.str(offer.id.as_str()).str(":").int(offer.price).str(",");
        }
        writer.str("\\n");
    }
    writer.str("event_relics=");""",
            'hash shop')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)
print('done')
