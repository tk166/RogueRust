"""§303 `wing_boots`：忽略路径约束、直接选下一层的任意房间（3 次）。

## wiki 口径（两处独立来源一致）

> *"It allows the player to select any room on the next floor when picking a Map Location,
> regardless of whether it's connected to the player's current Map Location or not. This can be
> done a maximum of **3** times before the relic becomes unusable."*

fandom 的描述同一件事：*"You may ignore paths when choosing the next room to travel to 3
times."* —— **两份来源都没有提到"每幕重置"**，所以不做重置：3 次是这一局的总次数。
（"每层 3 次"那种实现要发明一条两份来源都没有的规则，而且会让"用完了"这件事在换幕后
悄悄复活。）

## 切口：`reachable()`

页面点一个房间 → `rd_run_step(index)` → `enter_node(target)`，而 `enter_node` 只认
`reachable()` 里的目标。所以"可以选下一层的任意房间"= **`reachable()` 里多出那些房间**，
`enter_node` 里少一条"必须相邻"的判断。

⚠️ 追加在**后面**：与当前节点真连着的房间仍然排在最前面、下标不变 —— 否则既有测试与
页面的动作下标会整排位移（`reachable()[0]` 是页面最常点的那个）。

## 去哪**不**消耗次数

* 真连着的房间：免费（这条路本来就通）；
* Boss（第 16 层，`BOSS_NODE` 哨兵）：不在"下一层的房间"里，而且它只有一条路，所以
  不消耗 —— 否则"最后一个节点用飞行"会白烧一次。

## 计数进指纹与存档

`wing_boots_used` 是运行层状态：同一颗种子重放必须走同一条路，而"还能飞几次"会影响
后面每一次 `reachable()`。所以它进 `hash`（`wb=`）与存档（`VERSION` 9 → 10）。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── ① 变体 + 常量 + 表项
    patch(STATE, '''    /// §301：`neows_lament` —— 前 `fights` 场战斗里敌人的血量被**覆盖**成 `health`。''',
                '''    /// §303：`wing_boots` —— 地图上可以**忽略路径**、直接选下一层的任意房间，
    /// 一共 `uses` 次（wiki 两处来源都写 3，都没提"每幕重置" ⇒ 这是全局次数）。
    WingBoots {
        /// 这一局能飞几次。
        uses: u8,
    },
    /// §301：`neows_lament` —— 前 `fights` 场战斗里敌人的血量被**覆盖**成 `health`。''')

    patch(STATE, '''/// §301：`neows_lament` —— "Enemies in your first **3** combats will have **1** HP"。''',
                '''/// §303：`wing_boots` —— "select any room on the next floor … a maximum of **3** times"。
pub const WING_BOOTS_USES: u8 = 3;
/// §301：`neows_lament` —— "Enemies in your first **3** combats will have **1** HP"。''')

    patch(STATE, '''            // §302：`strange_spoon` —— 战斗内的开关（`plan` 的落区那一格读它）。''',
                '''            // §303：`wing_boots` —— 运行层的地图规则（没有内容状态）。
            "wing_boots" => Some(RelicEffect::WingBoots {
                uses: WING_BOOTS_USES,
            }),
            // §302：`strange_spoon` —— 战斗内的开关（`plan` 的落区那一格读它）。''')

    # ── ② 字段 + 初始化
    patch(STATE, '''    /// §301：这一局**已经打过几场**（开战时 +1）。`neows_lament` 用它数"前 3 场"。''',
                '''    /// §303：`wing_boots` **已经飞过几次**（只数真的"忽略路径"的那几步）。
    wing_boots_used: u8,
    /// §301：这一局**已经打过几场**（开战时 +1）。`neows_lament` 用它数"前 3 场"。''')
    patch(STATE, '''            pickup_offer_len: 0,
            fights: 0,''', '''            pickup_offer_len: 0,
            wing_boots_used: 0,
            fights: 0,''')

    # ── ③ 访问器 + "还能飞吗" + 下一层的全部房间
    patch(STATE, '''    /// §301：这一局已经打过几场（开战时 +1）。''',
                '''    /// §303：`wing_boots` 还能飞几次（没有遗物时恒 0）。
    #[must_use]
    pub fn wing_boots_left(&self) -> u8 {
        let Some(RelicEffect::WingBoots { uses }) = self.first_relic_effect_of(RelicEffect::WingBoots {
            uses: WING_BOOTS_USES,
        }) else {
            return 0;
        };
        uses.saturating_sub(self.wing_boots_used)
    }

    /// §303：这一步**能不能飞** —— 也就是"站在地图里、还有次数、下一层真的有房间"。
    ///
    /// Boss（第 16 层哨兵）不算：它不在"下一层的房间"里，只有一条路，飞过去等于白烧一次。
    #[must_use]
    fn may_ignore_paths(&self) -> bool {
        self.wing_boots_left() > 0
            && self.node >= 0
            && self.node != i32::from(crate::map::BOSS_NODE)
            && self.floor < ROWS as i32
    }

    /// §303：下一层的**全部**房间（不分连不连着）。`wing_boots` 用。
    fn all_next_row_nodes(&self) -> Reachable {
        let mut out = Reachable::default();
        let target_row = self.floor as usize;
        if target_row >= ROWS {
            return out;
        }
        let Some(row) = self.map.row(target_row) else {
            return out;
        };
        let Some(first) = self.map.row_first(target_row) else {
            return out;
        };
        for local in 0..row.len() {
            out.push(first + local as u8);
        }
        out
    }

    /// §301：这一局已经打过几场（开战时 +1）。''')

    # ── ④ `reachable()`：追加"下一层的其它房间"
    patch(STATE, '''        for &edge in source.out_targets() {
            if let Some(global) = self.map.global_of(row_index + 1, edge as usize) {
                out.push(global);
            }
        }
        out
    }''', '''        for &edge in source.out_targets() {
            if let Some(global) = self.map.global_of(row_index + 1, edge as usize) {
                out.push(global);
            }
        }
        // ── §303：`wing_boots` —— 追加"下一层**其它**的房间"（真的连着的那些已经在上面、
        // 下标不变）。位置是**最后**：既有测试与页面最常点的 `reachable()[0]` 必须还是同一个节点。
        if self.may_ignore_paths() {
            let all = self.all_next_row_nodes();
            for index in 0..all.len() {
                if let Some(target) = all.get(index) {
                    if !out.contains(target) {
                        out.push(target);
                    }
                }
            }
        }
        out
    }''')

    # ── ⑤ `enter_node`：忽略路径的那一步要**扣一次**
    patch(STATE, '''    pub fn enter_node(&mut self, target: u8) -> Result<(), RunError> {
        if !self.reachable().contains(target) {
            return Err(RunError::NotReachable);
        }''', '''    pub fn enter_node(&mut self, target: u8) -> Result<(), RunError> {
        // §303：`wing_boots` 让"下一层不相连的房间"也合法 —— 但那一步要**扣一次**。
        //
        // 判断顺序：先看它是不是本来就通（免费），再看能不能飞（扣一次），都不行才拒绝。
        // 这样"能飞"永远不会让免费的路开始收费。
        let free = self.connected_nodes().contains(target);
        let flying = !free && self.may_ignore_paths() && self.all_next_row_nodes().contains(target);
        if !free && !flying {
            return Err(RunError::NotReachable);
        }''')

    # 扣次数放在**验证之后**（`check_invariants` 通过了才算走成）
    patch(STATE, '''        self.check_invariants()
    }

    /// §286：''', '''        if flying {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }
        self.check_invariants()
    }

    /// §286：''')

    # ── ⑥ 把 `reachable()` 里"真连着的那些"抽成 `connected_nodes()`
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

    # ── ⑦ hash + 存档
    patch(HASH, '''    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。''',
                '''    // §303：`wing_boots` 已经飞过几次（它会改变后面每一次 `reachable()`）。
    writer
        .str("wb=")
        .u32(u32::from(state.wing_boots_left()))
        .str("\\n");
    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。''')

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

    # ── ⑧ 内容遗物行
    import json
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    if not any(r['Id'] == 'wing_boots' for r in doc['Relics']):
        doc['Relics'].append({'Id': 'wing_boots', 'DisplayName': 'Wing Boots',
                              'RunPrograms': None, 'CombatRules': None, 'Rarity': 'Rare'})
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('wing_boots wired')


main()
