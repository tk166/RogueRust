"""§226 (part 5): wasm 选牌层认「复制」与「收窄清单」。

* `rd_env_choice_kind` 多一个数：`4` = 复制（`ChoiceThen::Copy`）；
* 新导出 `rd_env_choice_copies`（每张造几份 —— 页面要写"各复制 N 份"）；
* `rd_env_choice_count` / `rd_env_choice_confirm` / `pile_card_id(3, i)` 三处一律走
  `choice_legal`：**收窄过的问句**（Dual Wield 的 "Attack 或 Power"）合法选项比牌区少，
  "数牌区"和"列牌区"会让页面画出内核随后要拒绝的选项。
"""
import io

LIB = 'kernel/rd-wasm/src/lib.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(LIB, [
    # kind: 4 = Copy
    ('''            // §161.4: "take it into your hand and make it free" (Liquid Memories). A **new number**
            // rather than reusing one, because the page writes the sentence from it.
            ChoiceThen::ToHand => 3,''',
     '''            // §161.4: "take it into your hand and make it free" (Liquid Memories). A **new number**
            // rather than reusing one, because the page writes the sentence from it.
            ChoiceThen::ToHand => 3,
            // §226: **copy** what was picked (Dual Wield). Again a new number: "复制" is a different
            // sentence from "拿进手牌", and the copies are printed-price (no `cost_delta`).
            ChoiceThen::Copy => 4,'''),

    # copies 导出（插在 kind 之后、source 之前）
    ('''/// Where the options come from: `1` a pile of cards, `2` three offered card definitions,''',
     '''/// How many copies of each picked card a `Copy` question makes; `0` when it is not a copy
/// question, `-1` when nothing is pending.
///
/// §226: the page has to be able to say "各复制 2 份" -- the number is the **content's** (base row 1,
/// `+` row 2), so it must travel from the kernel instead of being inferred from the `+`.
#[no_mangle]
pub extern "C" fn rd_env_choice_copies() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .state
        .pending_choice()
        .map_or(-1, |choice| i32::from(choice.copies))
}

/// Where the options come from: `1` a pile of cards, `2` three offered card definitions,'''),

    # count 走 choice_legal
    ('''    // §161.5: an `Offered` question counts **definitions**, not cards in a pile.
    match choice.source.zone() {
        Some(zone) => session
            .state
            .card_zones(&choice.chooser)
            .map_or(-1, |zones| zones.count(zone) as i32),
        None => choice.offered.len() as i32,
    }
}''',
     '''    // §161.5: an `Offered` question counts **definitions**, not cards in a pile.
    if choice.source.zone().is_none() {
        return choice.offered.len() as i32;
    }
    // §226: a pile question can be **narrowed** ("an Attack or Power card"), so the count is the
    // kernel's `choice_legal`, not the pile size. Counting the pile would paint options that
    // `resolve_choice` then refuses -- and the page's tick indices would be off by the filter.
    let mut buffer = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
    match session.state.choice_legal(&mut buffer) {
        Ok(count) => count as i32,
        Err(_) => -1,
    }
}'''),

    # confirm：牌区分支用 choice_legal 列选项
    ('''    let count = zones.count(zone);
    // Same enumeration the picker used (`rd_env_pile_len(3)`), and a loud cross-check that the slot
    // table and the card pool still line up. A silent `zip` over two lists of different lengths
    // would resolve a *different* question than the one that was asked.
    let ids: Vec<rd_core::state::CardInstanceId> = session
        .state
        .zone_cards(&choice.chooser, zone)
        .map(|card| card.id)
        .collect();
    if ids.len() != count {
        return refuse_with_text("牌的槽位表与卡池不一致：选牌清单不完整");
    }''',
     '''    // §226: **the same list the picker showed** -- `choice_legal`, not the pile. A narrowed
    // question (Dual Wield) has fewer legal cards than the pile has, and indexing into the pile
    // would resolve a different question than the one that was asked.
    let mut legal = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
    let legal_count = match session.state.choice_legal(&mut legal) {
        Ok(count) => count,
        Err(_) => return refuse_with_text("这个问句的选项读不出来"),
    };
    if legal_count == 0 {
        return refuse_with_text("这个问句没有合法选项");
    }
    let ids: Vec<rd_core::state::CardInstanceId> = legal[..legal_count].to_vec();'''),

    # pile_card_id(3, i) 走 choice_legal
    ('''    let session = ensure_session().ok()?;
    // The offered branch comes first: `pile_zone` legitimately answers `None` for it.
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered
                .get(index as usize)
                .map(|definition| definition.as_str().to_string());
        }
    }''',
     '''    let session = ensure_session().ok()?;
    // The offered branch comes first: `pile_zone` legitimately answers `None` for it.
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered
                .get(index as usize)
                .map(|definition| definition.as_str().to_string());
        }
        // §226: a pile question can be **narrowed**, so option `index` is the `index`-th element of
        // `choice_legal` -- **not** the `index`-th card of the pile. Reading the pile here is how
        // the picker would show card A while the kernel's count/answer meant card B.
        let choice = session.state.pending_choice()?;
        let mut legal = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
        let count = session.state.choice_legal(&mut legal).ok()?;
        if index as usize >= count {
            return None;
        }
        let id = legal[index as usize];
        let slot = session.state.find_card(&choice.chooser, &id)?.1;
        return session
            .state
            .card(slot)
            .map(|card| card.definition_id.as_str().to_string());
    }'''),
])

print('ok wasm')
