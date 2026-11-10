"""§332：把两排新货架接到 ABI 上（页面按"读一段字节"渲染，与卡/遗物那两排同一形状）。

新增导出：

* `rd_run_shop_colorless_count` / `_id_len` / `_id_into` / `_price` / `rd_run_buy_colorless`
* `rd_run_shop_potion_count` / `_id_len` / `_id_into` / `_price` / `rd_run_buy_potion`

⚠️ 名字里不要出现 `card`：无色货架卖的是**牌**，但它的 ABI 组与有色卡分开（价格带不同、
购买函数不同）。页面靠这两个组把两排画成两行。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# 找一个已有导出的锚点：`rd_run_shop_relic_price` 之后插入两组。
ANCHOR = """#[no_mangle]
pub extern "C" fn rd_run_buy_card(slot: i32) -> i32 {"""

NEW_EXPORTS = '''/// §332：无色货架有几张（wiki：1 Uncommon + 1 Rare）。
#[no_mangle]
pub extern "C" fn rd_run_shop_colorless_count() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    session.state.shop().colorless().len() as i32
}

/// §332：无色货架第 `slot` 张的 id 长度。
#[no_mangle]
pub extern "C" fn rd_run_shop_colorless_id_len(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.shop().colorless().get(slot.max(0) as usize) {
        Some(offer) => offer.id.as_str().len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_shop_colorless_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_shop_colorless_id_into(slot: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match session.state.shop().colorless().get(slot.max(0) as usize) {
        Some(offer) => write_out(offer.id.as_str(), ptr),
        None => 0,
    }
}

/// §332：无色货架第 `slot` 张的**挂牌价**（`-1` = 已售）。
#[no_mangle]
pub extern "C" fn rd_run_shop_colorless_price(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    session
        .state
        .shop()
        .colorless()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| offer.price)
}

/// §332：买无色货架第 `slot` 张。
#[no_mangle]
pub extern "C" fn rd_run_buy_colorless(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let cards = match full_pool(content(), true) {
        Ok(cards) => cards,
        Err(message) => {
            let Some(session) = run_slot().as_mut() else {
                return -1;
            };
            return fail(session, &message);
        }
    };
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BUY, slot, -1, "");
    match session.state.buy_colorless(slot as usize, &cards) {
        Ok(()) => 0,
        Err(e) => {
            let message = describe(&e);
            fail(session, &message)
        }
    }
}

/// §332：药水货架有几瓶（wiki：3）。
#[no_mangle]
pub extern "C" fn rd_run_shop_potion_count() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    session.state.shop().potions().len() as i32
}

/// §332：药水货架第 `slot` 瓶的 id 长度。
#[no_mangle]
pub extern "C" fn rd_run_shop_potion_id_len(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.shop().potions().get(slot.max(0) as usize) {
        Some(offer) => offer.id.as_str().len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_shop_potion_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_shop_potion_id_into(slot: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match session.state.shop().potions().get(slot.max(0) as usize) {
        Some(offer) => write_out(offer.id.as_str(), ptr),
        None => 0,
    }
}

/// §332：药水货架第 `slot` 瓶的挂牌价（`-1` = 已售）。
#[no_mangle]
pub extern "C" fn rd_run_shop_potion_price(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    session
        .state
        .shop()
        .potions()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| offer.price)
}

/// §332：买药水货架第 `slot` 瓶。
#[no_mangle]
pub extern "C" fn rd_run_buy_potion(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BUY, slot, -1, "");
    match session.state.buy_potion(slot as usize) {
        Ok(()) => 0,
        Err(e) => {
            let message = describe(&e);
            fail(session, &message)
        }
    }
}

#[no_mangle]
pub extern "C" fn rd_run_buy_card(slot: i32) -> i32 {'''

t = sub(t, ANCHOR, NEW_EXPORTS, 'exports')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('ABI: colorless + potion shelves')
