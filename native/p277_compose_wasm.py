"""§277 第二部分：建战斗时解析组合槽（加权掷骰，seed 派生）。

改动只在 `build_session_at_with` 的敌人循环里：每条记录先看 `Candidates`，
是组合槽就挑一个，然后用**被挑中的那条记录**继续走原来的路径（id / MaxHealth / MaxHealthAsc /
Spawn / Owner 全部照旧）—— 所以"组合"与"固定"共用同一段代码，不是第二条构建路径。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


PICKER = '''/// §277：`Candidates` 的加权抽取 —— 用**这一场战斗的 seed** 派生。
///
/// 为什么不开一条新的 `RunStream`：遭遇已经在 `RunStream::Combat` 上滚过一次，组合属于
/// "把这场战斗搭出来"（`Rolls` 初始化计数器也在同一层）。新开一条流只会让 `run_hash` 的
/// 随机流计数多一格，而那一格不影响任何运行层状态。判据是"同一个 seed 永远同一场"。
///
/// 实现刻意是**一个 splitmix 步**：够均匀、无状态、可复现，且不依赖任何一个 RNG 结构体。
fn pick_candidate(seed: i32, slot: usize, weights: &[i32]) -> usize {
    let total: i64 = weights.iter().map(|w| i64::from((*w).max(1))).sum();
    if total <= 0 {
        return 0;
    }
    let mut x = (seed as u32)
        .wrapping_add((slot as u32).wrapping_mul(0x9E37_79B9))
        .wrapping_add(0x85EB_CA6B);
    x ^= x >> 16;
    x = x.wrapping_mul(0x7FEB_352D);
    x ^= x >> 15;
    let roll = i64::from(x % (total as u32)) as i64;
    let mut edge = 0i64;
    for (index, weight) in weights.iter().enumerate() {
        edge += i64::from((*weight).max(1));
        if roll < edge {
            return index;
        }
    }
    weights.len().saturating_sub(1)
}

'''

OLD = '''        let spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;
        let id: &'static str = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;'''

NEW = '''        let spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;
        // §277：**组合槽** —— 这条记录可能只是"从这里挑一只"。挑中的那条与固定记录同形，
        // 所以下面整段原样复用（id / MaxHealth / MaxHealthAsc / Spawn / Owner）。
        let mut weight_list: Vec<i32> = Vec::new();
        let mut candidate_terms: Vec<u16> = Vec::new();
        {
            let candidates = spec
                .candidates()
                .map_err(|e| format!("ENCT enemy Candidates: {}", detail(&e)))?;
            for index in 0..candidates.len() {
                let element = candidates
                    .term(index)
                    .ok_or_else(|| "ENCT enemy Candidates: malformed element".to_string())?;
                let candidate = rd_core::content::EnemySpec::from_term(content, element);
                weight_list.push(
                    candidate
                        .weight()
                        .map_err(|e| format!("ENCT enemy Weight: {}", detail(&e)))?
                        .unwrap_or(1),
                );
                candidate_terms.push(element);
            }
        }
        let chosen = if candidate_terms.is_empty() {
            spec
        } else {
            let slot_index = seen_ids.len();
            let pick = pick_candidate(seed, slot_index, &weight_list);
            rd_core::content::EnemySpec::from_term(content, candidate_terms[pick])
        };
        let spec = chosen;
        let id: &'static str = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;'''


def main():
    src = io.open(P, encoding='utf-8').read()
    anchor = 'fn build_session_at_with('
    assert src.count(anchor) == 1
    if 'fn pick_candidate(' not in src:
        src = src.replace(anchor, PICKER + anchor)
    src = patch(src, OLD, NEW, 'composition in the planner')
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('rd-wasm: composition resolved at plan time')


main()
