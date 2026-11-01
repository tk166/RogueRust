"""§163.2 part 2: one `log(...)` line per mutating export, plus the three replay exports.

Every line is placed right after the export has its session, so the record carries the arguments the
caller used. `finish` stamps the hash afterwards (previous patch), which is why none of these lines
has to know about hashing.

`rd_run_script_len` / `rd_run_script_into` dump the journal as **one line**, `;`-separated:
`RDR1,seed,asc;kind,a,b,hash16,text;…`. `rd_run_replay_from` re-executes it and returns the index of
the **first** step whose hash differs (0 = the whole script reproduced).
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

# (function signature fragment, the log line to insert right after it)
SITES = [
    ("pub extern \"C\" fn rd_run_step(action_index: i32) -> i32 {",
     "    session.log(K_STEP, action_index, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_begin_node() -> i32 {",
     "    session.log(K_BEGIN, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_rest() -> i32 {",
     "    session.log(K_REST, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_open_chest() -> i32 {",
     "    session.log(K_CHEST, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_leave() -> i32 {",
     "    session.log(K_LEAVE, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_buy_card(slot: i32) -> i32 {",
     "    session.log(K_BUY_CARD, slot, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_buy_relic(slot: i32) -> i32 {",
     "    session.log(K_BUY_RELIC, slot, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_remove_card(index: i32) -> i32 {",
     "    session.log(K_REMOVE, index, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_take_card(slot: i32) -> i32 {",
     "    session.log(K_TAKE_CARD, slot, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_skip_reward() -> i32 {",
     "    session.log(K_SKIP, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_take_potion() -> i32 {",
     "    session.log(K_TAKE_POTION, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_take_relic() -> i32 {",
     "    session.log(K_TAKE_RELIC, -1, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_choose(slot: i32) -> i32 {",
     "    session.log(K_CHOOSE, slot, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_pick_event_card(index: i32) -> i32 {",
     "    session.log(K_EVENT_CARD, index, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_choose_start(slot: i32) -> i32 {",
     "    session.log(K_CHOOSE_START, slot, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_pick_blessing_card(index: i32) -> i32 {",
     "    session.log(K_BLESSING_CARD, index, -1, \"\");"),
    ("pub extern \"C\" fn rd_run_drop_potion(index: i32) -> i32 {",
     "    session.log(K_DROP_POTION, index, -1, \"\");"),
]

# `smith` and `grant_potion` carry a string.
SMITH = ("pub extern \"C\" fn rd_run_smith(index: i32) -> i32 {",
         "    session.log(K_SMITH, index, -1, \"\");")

EXPORTS = '''
// =============================================================================================
// §163 回放：脚本导出与逐步对拍
// =============================================================================================

fn script_text(session: &RunSession) -> std::string::String {
    let mut out = std::string::String::new();
    std::string::String::push_str(&mut out, "RDR1,");
    std::string::String::push_str(&mut out, &std::format!("{},{};", session.state.seed(), session.state.ascension()));
    for rec in &session.journal {
        std::string::String::push_str(&mut out, rec_kind_name(rec.kind));
        std::string::String::push_str(&mut out, &std::format!(",{},{},{:016x},", rec.a, rec.b, rec.hash));
        std::string::String::push_str(&mut out, &rec.text);
        std::string::String::push_str(&mut out, ";");
    }
    out
}

/// How long the script is (bytes); `-1` no run.
#[no_mangle]
pub extern "C" fn rd_run_script_len() -> i32 {
    match run_slot().as_ref() {
        Some(session) => script_text(session).len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_script_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_script_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let text = script_text(session);
    for (offset, &byte) in text.as_bytes().iter().enumerate() {
        *ptr.add(offset) = byte;
    }
    text.len() as i32
}

/// How many steps the last replay verified (`0` when it diverged at the first step).
#[no_mangle]
pub extern "C" fn rd_run_replay_checked() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.replay_checked as i32)
}

/// Where the last replay diverged: `0` = nowhere.
#[no_mangle]
pub extern "C" fn rd_run_replay_diverged() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.replay_diverged)
}

/// Apply a **recorded** fight outcome (the replay's path; a fight is never re-simulated).
fn replay_fight(session: &mut RunSession, hero_hp: i32, flags: i32) -> i32 {
    let elite = flags & 1 != 0;
    let boss = flags & 2 != 0;
    // A recorded fight is a **won** fight: a lost one ends the run, and a replay of a lost run ends
    // there too (`result` is read from the health that came back).
    let result = if hero_hp > 0 { 1 } else { 2 };
    apply_fight_outcome(session, hero_hp, result, elite, boss)
}

/// Replay the script in `(ptr, len)`. `0` = every step reproduced; `n > 0` = step `n` diverged;
/// `-1` no run slot; `-2` refused (parse error or a step the replay cannot apply) with text.
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_replay_from(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -2;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(text) = std::str::from_utf8(bytes) else {
        set_error("回放脚本不是 UTF-8");
        return -2;
    };
    // `RDR1,seed,asc;` first, then one record per step.
    let Some((head, rest)) = text.split_once(';') else {
        set_error("回放脚本缺少头部");
        return -2;
    };
    let Some(fields) = head.strip_prefix("RDR1,") else {
        set_error("回放脚本的头部不是 RDR1");
        return -2;
    };
    let parts: std::vec::Vec<&str> = fields.split(',').collect();
    if parts.len() != 2 {
        set_error("回放脚本的头部应当是 RDR1,seed,asc");
        return -2;
    }
    let (Ok(seed), Ok(ascension)) = (parts[0].parse::<i32>(), parts[1].parse::<i32>()) else {
        set_error("回放脚本的 seed/asc 不是整数");
        return -2;
    };
    // 从头开一局（`rd_run_start` 会清会话、清日志），然后关掉记录。
    if rd_run_start(seed, ascension) != 0 {
        return -2;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.replaying = true;

    let mut checked = 0usize;
    for (index, record) in rest.split(';').enumerate() {
        if record.is_empty() {
            continue;
        }
        let cells: std::vec::Vec<&str> = record.split(',').collect();
        if cells.len() < 4 {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的格式不对", index + 1));
            return (index + 1) as i32;
        }
        let Some(kind) = rec_kind_from_name(cells[0]) else {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的种类 `{}` 不认识", index + 1, cells[0]));
            return (index + 1) as i32;
        };
        let (Ok(a), Ok(b), Ok(want)) = (
            cells[1].parse::<i32>(),
            cells[2].parse::<i32>(),
            u64::from_str_radix(cells[3], 16),
        ) else {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的参数不是整数", index + 1));
            return (index + 1) as i32;
        };
        let payload = cells.get(4).copied().unwrap_or("");

        // 走**同一个**入口：拒绝与接受都由导出的函数自己决定，回放不重写规则。
        match kind {
            K_STEP => {
                let _ = rd_run_step(a);
            }
            K_BEGIN => {
                let _ = rd_run_begin_node();
            }
            K_REST => {
                let _ = rd_run_rest();
            }
            K_CHEST => {
                let _ = rd_run_open_chest();
            }
            K_LEAVE => {
                let _ = rd_run_leave();
            }
            K_BUY_CARD => {
                let _ = rd_run_buy_card(a);
            }
            K_BUY_RELIC => {
                let _ = rd_run_buy_relic(a);
            }
            K_REMOVE => {
                let _ = rd_run_remove_card(a);
            }
            K_TAKE_CARD => {
                let _ = rd_run_take_card(a);
            }
            K_SKIP => {
                let _ = rd_run_skip_reward();
            }
            K_TAKE_POTION => {
                let _ = rd_run_take_potion();
            }
            K_TAKE_RELIC => {
                let _ = rd_run_take_relic();
            }
            K_CHOOSE => {
                let _ = rd_run_choose(a);
            }
            K_EVENT_CARD => {
                let _ = rd_run_pick_event_card(a);
            }
            K_CHOOSE_START => {
                let _ = rd_run_choose_start(a);
            }
            K_BLESSING_CARD => {
                let _ = rd_run_pick_blessing_card(a);
            }
            K_DROP_POTION => {
                let _ = rd_run_drop_potion(a);
            }
            K_SMITH => {
                let _ = rd_run_smith(a, payload.as_ptr(), payload.len() as i32);
            }
            K_FIGHT_END => {
                let Some(session) = run_slot().as_mut() else {
                    return -1;
                };
                let _ = replay_fight(session, a, b);
            }
            _ => {}
        }

        let Some(session) = run_slot().as_ref() else {
            return -1;
        };
        let now = hash_prefix(&session.state).unwrap_or(0);
        if now != want {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!(
                "第 {} 步之后局面不同（期望 {want:016x}，回放得到 {now:016x}）",
                index + 1
            ));
            return (index + 1) as i32;
        }
        checked += 1;
    }
    session_clear_replay(checked, 0);
    0
}

fn session_clear_replay(checked: usize, diverged: i32) {
    if let Some(session) = run_slot().as_mut() {
        session.replaying = false;
        session.replay_checked = checked;
        session.replay_diverged = diverged;
    }
}
'''


def main():
    text = io.open(PATH, encoding="utf-8").read()

    for signature, line in SITES:
        assert text.count(signature) == 1, signature
        start = text.index(signature)
        # insert right after the signature's own `let Some(session) = run_slot()...` line
        probe = text.index("run_slot()", start)
        end = text.index("\n", probe) + 1
        text = text[:end] + line + "\n" + text[end:]

    # `smith` takes only the deck index (the upgraded id is derived inside), so it logs like the rest
    assert text.count(SMITH[0]) == 1
    start = text.index(SMITH[0])
    probe = text.index("run_slot()", start)
    end = text.index("\n", probe) + 1
    text = text[:end] + SMITH[1] + "\n" + text[end:]

    anchor = "/// The **kind** of a card the run is showing"
    assert text.count(anchor) == 1
    text = text.replace(anchor, EXPORTS.strip() + "\n\n" + anchor)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("18 log sites + 5 replay exports")


if __name__ == "__main__":
    main()
