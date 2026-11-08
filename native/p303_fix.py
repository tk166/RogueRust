"""§303 收尾：第一次脚本在第 ⑤ 步的第二个锚点上失败（下一个文档注释不是 §286）。

已经落地：变体 / 常量 / 表项 / 字段 / 访问器 / `reachable` 追加 / `enter_node` 的受理判断。
补：`connected_nodes()`、扣次数、三处 `match` 清单、hash、存档、内容行。
"""
import io
import json

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 扣次数：放在"验过 probe"之后（`climbed` 那段之前）
    patch(STATE, '''        probe.check_invariants()?;
        let climbed = probe.floor > self.floor;''',
                '''        probe.check_invariants()?;
        // §303：飞行这一步**现在才算数**（前面所有校验都过了、游标真的要动）。
        if flying {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }
        let climbed = probe.floor > self.floor;''')

    # ── ② `connected_nodes()`：把 reachable 里"真的连着"那半抽出来
    patch(STATE, '''    pub fn reachable(&self) -> Reachable {''',
                '''    /// §303：与当前节点**真的连着**的下一层房间（`wing_boots` 之外的正常路径）。
    ///
    /// 从 [`Self::reachable`] 里抽出来，是因为 [`Self::enter_node`] 需要"这一步是免费还是
    /// 飞行"这个区分，而**两个答案必须来自同一处** —— 否则"能点的"和"免费的"会漂。
    fn connected_nodes(&self) -> Reachable {
        let mut out = Reachable::default();
        if self.pending != Pending::None || self.node < 0 {
            return out;
        }
        let target_row = self.floor as usize;
        if target_row >= ROWS {
            if !self.boss_beaten && self.node != i32::from(crate::map::BOSS_NODE) {
                out.push(crate::map::BOSS_NODE);
            }
            return out;
        }
        let Some(row) = self.map.row(target_row - 1) else {
            return out;
        };
        let Some((row_index, local)) = self.map.locate(self.node as u8) else {
            return out;
        };
        let Some(source) = row.node(local) else {
            return out;
        };
        for &edge in source.out_targets() {
            if let Some(global) = self.map.global_of(row_index + 1, edge as usize) {
                out.push(global);
            }
        }
        out
    }

    pub fn reachable(&self) -> Reachable {''')

    # ── ③ 三处 `match` 清单
    patch(STATE, '''            | RelicEffect::PotionEffectPercent(_)
            // §301：`neows_lament` 在**开战那一刻**生效（由调用方问 `enemy_health_override`）。
            | RelicEffect::EnemyHealthInFirstFights { .. }
            | RelicEffect::RestCardReward => {}''',
                '''            | RelicEffect::PotionEffectPercent(_)
            // §301：`neows_lament` 在**开战那一刻**生效（由调用方问 `enemy_health_override`）。
            | RelicEffect::EnemyHealthInFirstFights { .. }
            // §303：`wing_boots` 只改地图的 `reachable()`，不参与任何"拿到那一刻"的效果。
            | RelicEffect::WingBoots { .. }
            | RelicEffect::RestCardReward => {}''')

    s = io.open(STATE, encoding='utf-8').read()
    lines = s.split('\n')
    targets = [i for i, line in enumerate(lines)
               if line.strip() == '| RelicEffect::EnemyHealthInFirstFights { .. },']
    assert len(targets) == 2, len(targets)
    for i in reversed(targets):
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = lines[i].rstrip()[:-1]
        lines[i + 1:i + 1] = [f'{indent}// §303：`wing_boots` 也不是这两个钩子上的事。',
                             f'{indent}| RelicEffect::WingBoots {{ .. }},']
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))

    # ── ④ hash
    patch(HASH, '''    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。''',
                '''    // §303：`wing_boots` 还能飞几次（它会改变后面每一次 `reachable()`）。
    writer
        .str("wb=")
        .u32(u32::from(state.wing_boots_left()))
        .str("\\n");
    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。''')

    # ── ⑤ 存档
    patch(ARCHIVE, '''/// §301：8 → 9（`fights`）。''', '''/// §303：9 → 10（`wing_boots_used`）。
/// §301：8 → 9（`fights`）。''')
    patch(ARCHIVE, '''const VERSION: u8 = 9;''', '''const VERSION: u8 = 10;''')
    patch(ARCHIVE, '''    // §301：已经打过几场（`neows_lament` 的"前 3 场"就靠这个数）。
    writer.byte(state.fights())?;''', '''    // §303：`wing_boots` 已经飞过几次。
    writer.byte(state.wing_boots_used)?;
    // §301：已经打过几场（`neows_lament` 的"前 3 场"就靠这个数）。
    writer.byte(state.fights())?;''')
    patch(ARCHIVE, '''    // §301
    let fights = reader.byte()?;''', '''    // §303
    let wing_boots_used = reader.byte()?;
    // §301
    let fights = reader.byte()?;''')
    patch(ARCHIVE, '''    restored.fights = fights;''', '''    restored.wing_boots_used = wing_boots_used;
    restored.fights = fights;''')

    # ── ⑥ 内容
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    if not any(r['Id'] == 'wing_boots' for r in doc['Relics']):
        doc['Relics'].append({'Id': 'wing_boots', 'DisplayName': 'Wing Boots',
                              'RunPrograms': None, 'CombatRules': None, 'Rarity': 'Rare'})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('wing_boots finished')


main()
