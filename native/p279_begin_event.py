"""§279：`rd_run_begin_event` —— 打开指定事件的调试入口。

理由与 `rd_run_grant_potion` 一样：**种子不会恰好给你想要的事件**。`?` 房要掷骰、
一幅地图上未必有 `?`、`?` 又要按三幕池子抽 —— 而"条件选项的画法"恰恰需要
`forgotten_altar` 这一屏。没有这个入口，页面上的条件逻辑只能靠单元测试。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 记录种类（进回放脚本：它改运行层，和 grant_potion 同一个理由）
    s = patch(s, '''const K_RECALL: u8 = 25;''','''const K_RECALL: u8 = 25;
// §279：打开**指定**事件（调试入口，理由同 `K_GRANT_POTION`）。
const K_BEGIN_EVENT: u8 = 26;''')
    s = patch(s, '''        K_RECALL => "recall",''','''        K_RECALL => "recall",
        K_BEGIN_EVENT => "begin_event",''')

    # ② 反查表（`rec_kind_from_name`）
    s = patch(s, '''        "recall" => K_RECALL,''','''        "recall" => K_RECALL,
        "begin_event" => K_BEGIN_EVENT,''')

    # ③ 导出本体（放在 grant_potion 的辅助函数之后：找一个唯一的锚点）
    s = patch(s, '''/// `EventEffect` as the same small integers the event ABI uses.''',
              '''/// 打开指定的 `?` 房事件。**For tests and the page's `?debug` surface only.**
///
/// 与 `rd_run_grant_potion` 同一条理由：种子不会恰好给你想要的那一屏。`?` 房要掷骰、
/// 地图上未必有 `?`、抽中的事件还要按三幕池子选 —— 而 §279 的条件选项只住在
/// `forgotten_altar` 那一屏上，没有这个入口就只能在单元测试里验它。
///
/// 它**不是** `cfg` 门：发货的 `.wasm` 与测过的必须是同一个二进制。
///
/// `0` 打开，`-1` 没有 run / 指针坏，`-2` 拒绝（没有这个事件、或当前节点已结算）。
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_begin_event(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -1;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(id) = std::str::from_utf8(bytes) else {
        return -2;
    };
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_BEGIN_EVENT, -1, -1, id);
    let Some(entry) = lookup_entry(id) else {
        let message = std::format!("`{id}` 不是内容的 EV 行");
        return fail(session, &message);
    };
    let outcome = session.state.begin_event(id, entry).map(|_| 0i32);
    finish(session, outcome)
}

/// `EventEffect` as the same small integers the event ABI uses.''')

    # ④ 回放分派
    s = patch(s, '''            K_GRANT_POTION => {
                let _ = rd_run_grant_potion(payload.as_ptr(), payload.len() as i32);
            }''','''            K_GRANT_POTION => {
                let _ = rd_run_grant_potion(payload.as_ptr(), payload.len() as i32);
            }
            K_BEGIN_EVENT => {
                let _ = rd_run_begin_event(payload.as_ptr(), payload.len() as i32);
            }''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd_run_begin_event added')


main()
