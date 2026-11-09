"""§320：`rd-wasm` 侧 —— 填 `PoolCard::colorless`、效果码、以及候选列表的四个导出。"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'

def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)

t = io.open(WASM, encoding='utf-8').read()

# ── 1. `full_pool`：无色标记（唯一看得见 `CARD.Tags` 的一层）───────────────────────
t = sub(t, """            kind: rd_run::state::CardKind::Other,
            upgraded: None,
        });
    }
    // 第二趟：把 `kind` 与 `upgraded` 填上。""",
        """            kind: rd_run::state::CardKind::Other,
            upgraded: None,
            // §320：`Sensory Stone` 的候选只从带这个 tag 的行里抽。事实来自内容，
            // 所以只能在这里填（`rd-run` 不读内容）。
            colorless: content.card_has_tag(id, "colorless") == Some(true),
        });
    }
    // 第二趟：把 `kind` 与 `upgraded` 填上。""",
        'full_pool colorless')

# ── 2. 药水的按 tag 池（`choice_offered`）────────────────────────────────────────
t = sub(t, """                pool.push(rd_run::state::PoolCard {
                    id,
                    rarity,
                    kind: rd_run::state::CardKind::Other,
                    upgraded: None,
                });""",
        """                pool.push(rd_run::state::PoolCard {
                    id,
                    rarity,
                    kind: rd_run::state::CardKind::Other,
                    upgraded: None,
                    // §320：这个池子按 `attack`/`skill` 过滤，而 `swift_strike` 这类牌
                    // 同时带 `colorless` —— 标记照内容填，别按"这个池子大概没有"猜。
                    colorless: image.card_has_tag(id, "colorless") == Some(true),
                });""",
        'potion pool colorless')

# ── 3. `colorless_card_pool` ────────────────────────────────────────────────────
t = sub(t, """        pool.push(rd_run::state::PoolCard {
            id,
            rarity,
            kind: rd_run::state::CardKind::Other,
            upgraded: None,
        });
    }
    Ok(pool)
}""",
        """        pool.push(rd_run::state::PoolCard {
            id,
            rarity,
            kind: rd_run::state::CardKind::Other,
            upgraded: None,
            // 这个池子**只**装带 `colorless` tag 的行（上面刚筛过）。
            colorless: true,
        });
    }
    Ok(pool)
}""",
        'colorless_card_pool flag')

# ── 4. 效果码 ───────────────────────────────────────────────────────────────────
t = sub(t, """        // §319：`remove_card_random:<kind>` 也一样 —— 类型名在**内容字符串**里（`Land` /
        // `Channel` / `Strike` 三个按钮的名字已经把它写在脸上了），枚举这边只剩下一个类。
        | EventEffect::RemoveCardRandom(_) => -1,""",
        """        // §319：`remove_card_random:<kind>` 也一样 —— 类型名在**内容字符串**里（`Land` /
        // `Channel` / `Strike` 三个按钮的名字已经把它写在脸上了），枚举这边只剩下一个类。
        | EventEffect::RemoveCardRandom(_)
        // §320：候选列表的落点是**候选面板**（`rd_run_event_offer_*`），不是效果码 ——
        // 张数与口径走 `effect_amount`（下面）与内容字符串。
        | EventEffect::OfferCards(_, _) => -1,""",
        'effect_code_of offer')

t = sub(t, """        // §319：类型不是"数量"。
        | EventEffect::RemoveCardRandom(_)
        | EventEffect::HealFull => 0,""",
        """        // §320：候选的张数就是"数量"（页面写"20 张里选一张"）。
        EventEffect::OfferCards(count, _) => i32::from(count),
        // §319：类型不是"数量"。
        | EventEffect::RemoveCardRandom(_)
        | EventEffect::HealFull => 0,""",
        'effect_amount offer')

# ── 5. 四个导出（候选面板）──────────────────────────────────────────────────────
t = sub(t, """/// The Ascension level this run is played at""",
        """/// §320：事件摊开的候选有几张（没有候选 ⇒ `0`；没有 run ⇒ `-1`）。
///
/// 页面用它决定**画不画**候选面板 —— 与 `rd_run_event_option_count` 同一条规矩：数量由运行层
/// 说，页面不猜。
#[no_mangle]
pub extern "C" fn rd_run_event_offer_len() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |session| session.state.event_offer_len() as i32)
}

/// §320：候选 `slot` 的牌 id 长度（`-1` = 没有这个槽）。
#[no_mangle]
pub extern "C" fn rd_run_event_offer_id_len(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if slot < 0 {
        return -1;
    }
    match session.state.event_offer_card(slot as usize) {
        Some(id) => id.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_offer_id_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_offer_id_into(slot: i32, ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    if slot < 0 {
        return 0;
    }
    match session.state.event_offer_card(slot as usize) {
        Some(id) => write_out(id, ptr),
        None => 0,
    }
}

/// §320：从候选里取走一张（`The Library` 的 20 选 1、`Sensory Stone` 的每次 Recall）。
///
/// `0` = 拿到，`-1` = 没有这个槽 / 没有 run，`-2` = 相位不对**或**牌组满了（`fail` 带原因）。
///
/// ⚠️ 池子必须**含无色牌**：`Sensory Stone` 的候选**就是**无色牌，用 `reward_pool`
/// （它按 §183/§185 剔掉无色）会在这里报 `NoSuchCard` —— 一个"池子选错了"的错，
/// 而屏幕上只会显示"取牌失败"。
#[no_mangle]
pub extern "C" fn rd_run_event_offer_take(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_EVENT_CARD, slot, -1, "offer");
    let pool = match full_pool(content(), true) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .pick_event_offer(slot as usize, &pool)
        .map(|_| 0i32);
    finish(session, outcome)
}

/// The Ascension level this run is played at""",
        'offer exports')

io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm patched')
