"""§331：给 `roll_event_relic_offer` 加一个**仅测试**的入口。

生产路径在 `rd_run_begin_node` 里（那里拿得到 `entry`），而测试要"先开事件、再单独看候选"。
不复制掷法 —— 复制出来的第二份一定会漂（`FACT.md` §4.20）。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'

ANCHOR = "/// Rest: heal 30% of maximum HP. Returns the health restored, or `-2`."

HELPER = """/// §331（**仅测试**）：把掷候选那一步单独暴露出来。
///
/// 生产路径是 `rd_run_begin_node` 里的一段（那里拿得到 `entry`），而测试要"先开事件、
/// 再单独看候选"，所以留一个只编译进 test 的入口 —— **不复制掷法**
/// （复制出来的第二份一定会漂，`FACT.md` §4.20）。
#[cfg(test)]
pub(crate) fn test_roll_event_relic_offer(count: u8) -> Result<(), String> {
    let Some(session) = run_slot().as_mut() else {
        return Err("no session".to_string());
    };
    roll_event_relic_offer(session, count)
}

"""

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, HELPER + ANCHOR))
print('test helper added')
