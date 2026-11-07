"""§259 第 4 层：ABI（5 个导出）+ 回放记录种类（4 个）。

设计：**选项用一个位掩码返回**（`rd_run_campfire_options`），而不是六个 `is_*_allowed` 导出 ——
页面一次渲染就要全部六个，六个导出意味着六次往返，而且"漏了一个导出"只表现为那个按钮永远不出现。

位序是硬约定（页面按它读），所以写在这里、也写在页面那一侧：Rest 1 / Smith 2 / Recall 4 /
Lift 8 / Toke 16 / Dig 32。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

EDITS = [
    # ---- 回放记录种类 ----
    ('''const K_GRANT_POTION: u8 = 21;''',
     '''const K_GRANT_POTION: u8 = 21;
// §259：篝火新增的四个动作。它们**进回放脚本**，所以"同一份脚本重放"也覆盖它们。
const K_LIFT: u8 = 22;
const K_TOKE: u8 = 23;
const K_DIG: u8 = 24;
const K_RECALL: u8 = 25;'''),
    ('''        K_GRANT_POTION => "grant_potion",
        _ => "?",''',
     '''        K_GRANT_POTION => "grant_potion",
        K_LIFT => "lift",
        K_TOKE => "toke",
        K_DIG => "dig",
        K_RECALL => "recall",
        _ => "?",'''),
    ('''        "grant_potion" => K_GRANT_POTION,''',
     '''        "grant_potion" => K_GRANT_POTION,
        // §259
        "lift" => K_LIFT,
        "toke" => K_TOKE,
        "dig" => K_DIG,
        "recall" => K_RECALL,'''),
    # ---- 五个导出：插在 `rd_run_open_chest` 之前（篝火一族挨在一起）----
    ('''/// Open the chest under the cursor. `0` = done; the gold and relic are in the run observation and
/// `rd_run_relic_*`.''',
     '''/// §259：篝火上有哪些选项，**一个位掩码**。
///
/// 位序是硬约定（页面按它读）：`Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 | Dig 32`。
/// 为什么不是六个 `is_*_allowed` 导出：页面一次渲染就要全部六个，六个导出是六次往返，而
/// "漏了一个导出"只表现为那个按钮永远不出现 —— 那是本仓库最恨的失败形态。
///
/// `-1` = 没有局；否则 `0..=63`。
#[no_mangle]
pub extern "C" fn rd_run_campfire_options() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let options = session.state.campfire_options();
    let mut bits = 0i32;
    for (flag, bit) in [
        (options.rest, 1),
        (options.smith, 2),
        (options.recall, 4),
        (options.lift, 8),
        (options.toke, 16),
        (options.dig, 32),
    ] {
        if flag {
            bits |= bit;
        }
    }
    bits
}

/// §259：`Lift`（`Girya`）。返回**累计用过几次**（1..=3），或 `-2`（拒绝）。
#[no_mangle]
pub extern "C" fn rd_run_lift() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_LIFT, -1, -1, "");
    let outcome = session.state.lift().map(i32::from);
    finish(session, outcome)
}

/// §259：`Toke`（`Peace Pipe`）—— 删掉牌组第 `index` 张。
#[no_mangle]
pub extern "C" fn rd_run_toke(index: i32) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_TOKE, index, -1, "");
    if index < 0 {
        return -1;
    }
    let outcome = session.state.toke(index as usize).map(|()| 0i32);
    finish(session, outcome)
}

/// §259：`Dig`（`Shovel`）—— 抽一件遗物（只 Common/Uncommon/Rare）。
///
/// 抽到的 id 通过 `rd_run_relic_slot` 系列读（与宝箱同一条路）：这里只返回 `0`，
/// 因为"抽到了哪件"属于观察，不属于返回值。
#[no_mangle]
pub extern "C" fn rd_run_dig() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_DIG, -1, -1, "");
    let relics = relic_pool(content());
    let outcome = session.state.dig(&relics).map(|_| 0i32);
    finish(session, outcome)
}

/// §259：`Recall` —— 拿红钥匙。
#[no_mangle]
pub extern "C" fn rd_run_recall() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_RECALL, -1, -1, "");
    let outcome = session.state.recall().map(|()| 0i32);
    finish(session, outcome)
}

/// Open the chest under the cursor. `0` = done; the gold and relic are in the run observation and
/// `rd_run_relic_*`.'''),
]


def main():
    src = io.open(RUN, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:60])
        src = src.replace(old, new)
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src)
    print('layer 4: %d edits' % len(EDITS))


main()
