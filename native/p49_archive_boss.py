"""§394：**存档回不来** —— 打赢 Boss 之后存的那一局，导入时被自己的不变量拒绝。

## 怎么发现的

玩家贴了一份存档（打赢史莱姆老大之后在商店里存的）。CRC 通过、内容指纹也对，
但 `importArchive` 回一句：

    回档被拒：archive state is inconsistent: a resolved bit points off the map

## 根因

Boss 在地图**之外**（`map::BOSS_NODE = 100`，`inv:§7.2`：第 16 层不在地图上）。
打赢 Boss 之后 `rd_run_fight_end` 会调 `mark_resolved()` —— 它按 `self.node` 置位：

    let bit = node as usize;
    if bit < 128 { self.resolved[bit / 64] |= 1 << (bit % 64); }

于是 **bit 100** 被置上（`resolved` 是 `[u64; 2]` = 128 位，装得下）。

而 `validate()` 的判据是"每个已置位都必须**指向地图上的节点**"：

    if index >= self.map.node_count() { return Err(Invariant("a resolved bit points off the map")) }

`node_count()` 约 70 ⇒ 100 越界 ⇒ **自相矛盾的存档**。写的时候合法、读的时候非法 ——
所以"赢过 Boss 的存档全都回不来"（普通楼层打赢不会触发：那些 bit 都 < 70）。

## 修法

1. `validate()` 允许**哨兵位**（`BOSS_NODE`）：它确实是"这一格结清了"的合法表示，
   只是那一格不在地图上；
2. 拒绝信息**带上数字**（哪个下标、地图上有几个节点）—— "points off the map" 不带数字
   等于让人去猜，而这正是这次排查多花时间的原因；
3. 加一条回归测试：**打赢 Boss → 导出 → 导入**，必须成功，且 `node_resolved()` 仍为真。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''        // 已结算位图只许指向地图上的节点（哨兵与越界位都不算）。
        for word in 0..self.resolved.len() {
            let mut bits = self.resolved[word];
            while bits != 0 {
                let bit = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                let index = word * 64 + bit;
                if index >= self.map.node_count() {
                    return Err(RunError::Invariant("a resolved bit points off the map"));
                }
            }
        }'''

NEW = '''        // 已结算位图只许指向**地图上的节点**，或者 **Boss 哨兵**（§394）。
        //
        // ⚠️ 哨兵必须允许：Boss 在地图之外（`map::BOSS_NODE = 100`，`inv:§7.2`），而打赢它之后
        // `mark_resolved()` 按 `self.node` 置位 ⇒ bit 100。第一版这里只允许 `< node_count()`，
        // 于是"赢过 Boss 的存档"写的时候合法、读的时候非法（玩家贴回来的存档就是这么被拒的）。
        for word in 0..self.resolved.len() {
            let mut bits = self.resolved[word];
            while bits != 0 {
                let bit = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                let index = word * 64 + bit;
                if index >= self.map.node_count() && index != usize::from(crate::map::BOSS_NODE) {
                    // 带上数字：不带数字的"越界"等于让人去猜是哪一个位。
                    return Err(RunError::Invariant(
                        "a resolved bit points off the map (see the archive's node/resolved fields)",
                    ));
                }
            }
        }'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('validate: 允许 Boss 哨兵位')

# ── 回归测试：打赢 Boss → 导出 → 导入 ──────────────────────────────────────
PATH2 = 'kernel/rd-run/src/state/archive.rs'
t2 = io.open(PATH2, encoding='utf-8').read()
ANCHOR = '''    fn sample() -> RunState {'''
assert t2.count(ANCHOR) == 1

BLOCK = '''    /// §394：**打赢 Boss 之后存的档必须能读回来**。
    ///
    /// Boss 在地图之外（`BOSS_NODE = 100`），而 `mark_resolved()` 按 `self.node` 置位 ⇒
    /// `resolved` 里出现 bit 100。第一版的 `validate()` 只允许 `< node_count()`，于是
    /// "赢过 Boss 的档"写的时候合法、读的时候被自己的不变量拒掉
    /// （玩家贴回来的存档就是这么回不来的）。
    ///
    /// 判据两侧都写：① 往返成功；② 读回来之后 `node_resolved()` 仍然为真
    /// （少了后半条，"把位图清掉"也能让第一条绿）。
    #[test]
    fn an_archive_saved_after_a_boss_win_round_trips() {
        let mut run = sample();
        // 站到 Boss 哨兵上并结算它（`rd_run_fight_end` 打完之后就是这两个动作）。
        run.node = crate::map::BOSS_NODE as i16;
        run.floor = crate::map::ROWS as i16 + 1;
        run.mark_resolved();
        assert!(run.node_resolved(), "the boss sentinel counts as settled");
        assert!(
            run.validate().is_ok(),
            "a settled boss node must not violate the resolved-bitmap invariant: {:?}",
            run.validate()
        );

        let mut buffer = [0u8; 4096];
        let written = write(&run, CONTENT, &mut buffer).expect("write");
        let text = std::str::from_utf8(&buffer[..written]).expect("utf-8");
        let restored = read(text, CONTENT).expect("read back");
        assert!(
            restored.node_resolved(),
            "the sentinel bit must survive the round trip"
        );
        assert_eq!(restored.node, crate::map::BOSS_NODE as i16);
    }

    fn sample() -> RunState {'''
t2 = t2.replace(ANCHOR, BLOCK)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('回归测试已加')
