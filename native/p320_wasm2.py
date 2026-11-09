"""§320 第二半 wasm：候选的**显示名**（页面要画牌名，不是 id）。

与 `rd_run_pickup_offer_title_*` 逐字同构，共用一个取名字函数（`deck_title`）——
两处各写一份名字映射就是那个经典漂。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'

OLD = """/// §320：从候选里取走一张（`The Library` 的 20 选 1、`Sensory Stone` 的每次 Recall）。"""

NEW = '''/// §320：候选 `slot` 的**显示名**长度（内容里的 `CARD` 行标题）。
#[no_mangle]
pub extern "C" fn rd_run_event_offer_title_len(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let Some(run) = run_slot().as_ref() else {
        return -1;
    };
    let Some(id) = run.state.event_offer_card(slot as usize) else {
        return -1;
    };
    // 与奖励屏/加牌候选同一个取名字函数 —— 两处各写一份就会漂。
    deck_title(content(), id).unwrap_or(id).len() as i32
}

/// §320：把候选 `slot` 的显示名写进 `ptr`（`rd_run_event_offer_title_len(slot)` 个字节）。
///
/// # Safety
///
/// `ptr` must point at that many writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_offer_title_into(slot: i32, ptr: *mut u8) -> i32 {
    if slot < 0 || ptr.is_null() {
        return -1;
    }
    let Some(run) = run_slot().as_ref() else {
        return -1;
    };
    let Some(id) = run.state.event_offer_card(slot as usize) else {
        return -1;
    };
    write_out(deck_title(content(), id).unwrap_or(id), ptr)
}

/// §320：从候选里取走一张（`The Library` 的 20 选 1、`Sensory Stone` 的每次 Recall）。'''


def main():
    t = io.open(WASM, encoding='utf-8').read()
    assert t.count(OLD) == 1, 'anchor'
    assert 'rd_run_event_offer_title_len' not in t, 'already patched'
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t.replace(OLD, NEW))
    print('title exports added')


main()
