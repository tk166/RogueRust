"""§270 wasm 侧：`full_pool` 填 kind/upgraded、按 id 取 PoolCard、两个 ABI 传牌、价格走折扣。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


HELPERS = '''/// §270：一张牌的**类型** —— 读 `Content::card_tag_bits`（"tag → 位图"的唯一映射，
/// `exec::CARD_HAS_TAG_*` 用的也是它），所以这里**不是**第二份类型词表。
///
/// ⚠️ 顺序即优先级：一张牌同时带 `attack` 与 `skill` 时归 Attack（内容里不存在这样的牌；
/// 真有的话"哪个蛋管它"就必须是一次显式决定，而不是靠 tag 表的插入顺序）。
fn card_kind(content: &'static Content<'static>, id: &str) -> rd_run::state::CardKind {
    use rd_core::exec;
    use rd_run::state::CardKind;
    let bits = content.card_tag_bits(id);
    if bits & exec::CARD_HAS_TAG_ATTACK != 0 {
        CardKind::Attack
    } else if bits & exec::CARD_HAS_TAG_SKILL != 0 {
        CardKind::Skill
    } else if bits & exec::CARD_HAS_TAG_POWER != 0 {
        CardKind::Power
    } else if bits & exec::CARD_HAS_TAG_CURSE != 0 {
        CardKind::Curse
    } else if bits & exec::CARD_HAS_TAG_STATUS != 0 {
        CardKind::Status
    } else {
        CardKind::Other
    }
}

'''

FULL_POOL_OLD = '''        let rarity = match content.card_rarity(id) {
            Some(name) => rd_run::state::Rarity::from_name(name)
                .ok_or_else(|| std::format!("卡 `{id}` 的 Rarity `{name}` 不认识"))?,
            None => return Err(std::format!("卡 `{id}` 没有 Rarity")),
        };
        pool.push(rd_run::state::PoolCard { id, rarity });
    }
    Ok(pool)
}'''

FULL_POOL_NEW = '''        let rarity = match content.card_rarity(id) {
            Some(name) => rd_run::state::Rarity::from_name(name)
                .ok_or_else(|| std::format!("卡 `{id}` 的 Rarity `{name}` 不认识"))?,
            None => return Err(std::format!("卡 `{id}` 没有 Rarity")),
        };
        pool.push(rd_run::state::PoolCard {
            id,
            rarity,
            // §270：类型（三个蛋与两条诅咒规则要它）与 `+` 行（三个蛋要它）。
            // ⚠️ 这里只填 id/rarity，`kind`/`upgraded` 在下面第二趟补 —— 因为 `+` 行要在
            // **整个池子**里找，而池子正是这一趟在攒的。
            kind: rd_run::state::CardKind::Other,
            upgraded: None,
        });
    }
    // 第二趟：把 `kind` 与 `upgraded` 填上。`upgraded` 走 `rd_run::state::upgraded_id` ——
    // A12（奖励升级）用的就是它，所以"什么是 `+` 行"**只有一处**答案。
    for index in 0..pool.len() {
        let id = pool[index].id;
        pool[index].kind = card_kind(content, id);
        pool[index].upgraded = rd_run::state::upgraded_id(&pool, id);
    }
    Ok(pool)
}'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① card_kind 助手（放在 full_pool 之前）
    src = patch(src, '''/// The cards a **reward screen** may offer.''',
                HELPERS + '''/// The cards a **reward screen** may offer.''', 'card_kind helper')

    # ② full_pool 填 kind/upgraded
    src = patch(src, FULL_POOL_OLD, FULL_POOL_NEW, 'full_pool')

    # ③ 按 id 取一张 PoolCard（`take_card` / `buy_card` 的调用方用它）
    src = patch(src, '''/// The reward pool: the same cards minus the upgraded rows''',
                '''/// §270：**一张**牌，按 id —— `take_card` / `buy_card` 要把"这一屏那一张"交给运行层
/// （三个蛋与两条诅咒规则要看类型）。走 `full_pool` 的同一个构造点，所以类型与 `+` 行的解析
/// 只有一处。
fn pool_card_by_id(
    content: &'static Content<'static>,
    id: &str,
) -> Result<rd_run::state::PoolCard<'static>, String> {
    full_pool(content)?
        .into_iter()
        .find(|card| card.id == id)
        .ok_or_else(|| std::format!("卡 `{id}` 不在池子里"))
}

/// The reward pool: the same cards minus the upgraded rows''', 'pool_card_by_id')

    # ④ ABI：take_card / buy_card 传牌
    src = patch(src, '''    let outcome = session.state.buy_card(slot as usize).map(|_| 0i32);''',
                '''    let Some(content) = session.content() else {
        return -1;
    };
    let Some(id) = session.state.shop().cards().get(slot as usize).map(|o| o.id) else {
        return -1;
    };
    let card = match pool_card_by_id(content, id.as_str()) {
        Ok(card) => card,
        Err(_) => return -1,
    };
    let outcome = session.state.buy_card(slot as usize, card).map(|_| 0i32);''',
                'buy_card ABI')

    src = patch(src, '''    let outcome = session.state.take_card(slot as usize).map(|_| 0i32);''',
                '''    let Some(content) = session.content() else {
        return -1;
    };
    let Some(id) = session.state.reward().cards().get(slot as usize).copied() else {
        return -1;
    };
    let card = match pool_card_by_id(content, id.as_str()) {
        Ok(card) => card,
        Err(_) => return -1,
    };
    let outcome = session.state.take_card(slot as usize, card).map(|_| 0i32);''',
                'take_card ABI')

    # ⑤ 商店价格走折扣（显示的数 = 扣的数）
    src = patch(src, '''    shop_offer(run_slot().as_ref(), slot, true).map_or(-1, |offer| offer.price)''',
                '''    // §270：显示价 = `shop_price(挂牌价)`，`buy_card` 扣的也是它 —— 两处同一个函数。
    let session = run_slot();
    let session = session.as_ref();
    shop_offer(session, slot, true)
        .map_or(-1, |offer| session.map_or(offer.price, |s| s.state.shop_price(offer.price)))''',
                'shop card price')

    src = patch(src, '''    shop_offer(run_slot().as_ref(), slot, false).map_or(-1, |offer| offer.price)''',
                '''    let session = run_slot();
    let session = session.as_ref();
    shop_offer(session, slot, false)
        .map_or(-1, |offer| session.map_or(offer.price, |s| s.state.shop_price(offer.price)))''',
                'shop relic price')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('run.rs: pool kinds + ABI card params + discounted prices')


main()
