"""§272 rd-run：`?` 房**分流**（wiki `Unknown Location`）+ `tiny_chest` / `juzu_bracelet`。

## 规则（三份独立来源一致）

| 结果 | 基础概率 | 每次"没出现" | 出现时 |
|---|---|---|---|
| Monster | 10% | +10 | 归零 |
| Shop | 3% | +3 | 归零 |
| Treasure | 2% | +2 | 归零 |
| Event | 其余（基础 85%） | —— | 不重置别的 |

一次性掷骰（`RunStream::Event`），前缀累加判定：`roll < monster` ⇒ Monster；
`roll < monster+shop` ⇒ Shop；`roll < monster+shop+treasure` ⇒ Treasure；否则 Event。
换幕时三个计数归零（wiki："The values for all types are reset in between acts"）。

* `juzu_bracelet`：去掉 Monster 那条掷骰（基础改为 0 ⇒ Event 变成 95%）。
* `tiny_chest`：每第 4 个 `?` 房强制 Treasure（同时把 treasure 计数归零）。

## 为什么掷骰**总是**掷

有没有 `tiny_chest` / `juzu_bracelet` 都会消耗一次 `Event` 流 —— 与 `sozu`（不发药水但掷骰照旧）、
`white_beast_statue`（必出药水但掷骰照旧）同一条纪律：**随机流的位置不随遗物变化**，
否则"同一串动作"在拿遗物前后就走到两条时间线上，回放会分叉。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


ENUM = '''/// §272：`?` 房的结果（wiki `Unknown Location`）。
///
/// 结果是**运行期状态**：`Event` 由调用方去开事件、`Monster` 由调用方开一场普通战斗，
/// 而 `Shop` / `Treasure` 在 `begin_node` 里当场变成 `Pending::Shop` / `Pending::Chest`。
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
pub enum UnknownRoom {
    /// 还没掷过（一个 `?` 房在 `begin_node` 之前）。
    #[default]
    Unresolved = 0,
    /// 一个事件（`begin_event`，`inv:§7.3`）。
    Event = 1,
    /// 一场**普通**战斗（用本幕的 `Weak*` 池，与战斗节点同一条路）。
    Monster = 2,
    /// 商人（当场摆货架）。
    Shop = 3,
    /// 宝箱（`Pending::Chest`）。
    Treasure = 4,
}

/// §272：`?` 房三条基础概率（wiki 的 10 / 3 / 2，单位 percent）。
pub const UNKNOWN_MONSTER_BASE: i32 = 10;
pub const UNKNOWN_SHOP_BASE: i32 = 3;
pub const UNKNOWN_TREASURE_BASE: i32 = 2;

/// §272：`tiny_chest` —— 每到第几个 `?` 房强制宝箱（wiki："Every 4th ? room"）。
pub const TINY_CHEST_ROOMS: u8 = 4;

'''

VARIANTS = '''    /// §272：`juzu_bracelet` —— `?` 房不再出**普通**战斗（wiki 原文：removes the 10% base chance）。
    NoUnknownMonster,
    /// §272：`tiny_chest` —— 每第 4 个 `?` 房是宝箱。
    TinyChestEveryFourth,'''

ROWS = '''            // §272：`?` 房分流的两件（规则在 `roll_unknown_room` 里）。
            "juzu_bracelet" => Some(RelicEffect::NoUnknownMonster),
            "tiny_chest" => Some(RelicEffect::TinyChestEveryFourth),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。'''

FIELDS = '''    /// §271：`ancient_tea_set` —— 刚进过篝火 ⇒ **下一场**战斗开战多 2 能量。
    ///
    /// 为什么是运行期字段、而不是"在篝火那一刻直接加能量"：那时没有战斗，能量无处可加
    /// （能量是战斗状态的资源）。所以只记"欠一场"，开战那一刻兑现、然后清掉。
    tea_set_pending: bool,
    /// §272：光标下那个 `?` 房**掷出了什么**（`begin_node` 之前是 `Unresolved`）。
    ///
    /// 为什么要有这个字段：`begin_node` 只能返回 `NodeKind`，而"事件"与"普通战斗"都是
    /// `NodeKind::Unknown` —— 调用方（`rd-wasm`）必须靠它区分"开事件"还是"开一场战斗"。
    unknown_room: UnknownRoom,
    /// §272：`tiny_chest` 已经数到第几个 `?` 房（0..`TINY_CHEST_ROOMS`）。只在这件遗物在
    /// 身上时增长；换幕归零（与三条概率同一个理由）。
    tiny_chest_rooms: u8,'''

ROLL = '''    /// §272：掷一次 `?` 房的结果，并把三条计数器按规则推进。
    ///
    /// 参数全在本结构体里（三条 `unknown` 计数、遗物表、随机流），所以它是**唯一**决定
    /// "`?` 房变成什么"的地方 —— `begin_node` 只是按结果摆好状态，不是第二个裁决者。
    pub fn roll_unknown_room(&mut self) -> Result<UnknownRoom, RunError> {
        // 三条基础概率 × (1 + 连续没出现次数)。`juzu_bracelet` 把 Monster 那条按成 0。
        let juzu = self.holds_relic_effect(RelicEffect::NoUnknownMonster);
        let monster = if juzu {
            0
        } else {
            (UNKNOWN_MONSTER_BASE * (1 + self.unknown[0])).min(100)
        };
        let shop = (UNKNOWN_SHOP_BASE * (1 + self.unknown[1])).min(100);
        let treasure = (UNKNOWN_TREASURE_BASE * (1 + self.unknown[2])).min(100);
        // **总是**掷一次（理由见 §272 的模块注释：随机流的位置不随遗物变化）。
        // ⚠️ 这一掷在下面所有写操作**之前**，所以 `Err` 时状态一个字节都没动。
        let roll = self.rng.roll(RunStream::Event, 100)? as i32;
        let mut outcome = if roll < monster {
            UnknownRoom::Monster
        } else if roll < monster + shop {
            UnknownRoom::Shop
        } else if roll < monster + shop + treasure {
            UnknownRoom::Treasure
        } else {
            UnknownRoom::Event
        };
        // §272：`tiny_chest` —— "Every 4th ? room is a Treasure room"。
        // 它**覆盖结果**而不是"再掷一次"：再掷一次会让"第 4 个"这个计数变得不可观察
        // （玩家看到的结果与计数对不上），而且要多烧一个随机数。
        if self.holds_relic_effect(RelicEffect::TinyChestEveryFourth) {
            self.tiny_chest_rooms += 1;
            if self.tiny_chest_rooms >= TINY_CHEST_ROOMS {
                self.tiny_chest_rooms = 0;
                outcome = UnknownRoom::Treasure;
            }
        } else {
            // 没有这件遗物时计数必须停在地上：否则"拿到它的那一刻"就凭空多出几次。
            self.tiny_chest_rooms = 0;
        }
        // 三条计数：命中的归零、其余 +1（wiki："increases whenever a `?` room does not contain
        // that type … If a shop is found, the shop chance will be reset back to 3%"）。
        match outcome {
            UnknownRoom::Monster => {
                self.unknown[0] = 0;
                self.unknown[1] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Shop => {
                self.unknown[1] = 0;
                self.unknown[0] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Treasure => {
                self.unknown[2] = 0;
                self.unknown[0] += 1;
                self.unknown[1] += 1;
            }
            UnknownRoom::Event => {
                self.unknown[0] += 1;
                self.unknown[1] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Unresolved => {}
        }
        self.unknown_room = outcome;
        Ok(outcome)
    }

    /// §272：三条概率**现在**是多少（percent），给页面与判据用。
    ///
    /// 与 [`Self::roll_unknown_room`] 用同一组常量与同一个公式 —— 页面上写的 10/3/2 必须与
    /// 真正掷骰的那三个数一致（否则玩家看到的是第三份定价）。
    #[must_use]
    pub fn unknown_room_odds(&self) -> [i32; 3] {
        let juzu = self.holds_relic_effect(RelicEffect::NoUnknownMonster);
        let monster = if juzu {
            0
        } else {
            (UNKNOWN_MONSTER_BASE * (1 + self.unknown[0])).min(100)
        };
        [
            monster,
            (UNKNOWN_SHOP_BASE * (1 + self.unknown[1])).min(100),
            (UNKNOWN_TREASURE_BASE * (1 + self.unknown[2])).min(100),
        ]
    }

    /// §272：光标下那个 `?` 房掷出了什么（`Unresolved` = 还没掷 / 不是 `?` 房）。
    #[must_use]
    pub const fn unknown_room(&self) -> UnknownRoom {
        self.unknown_room
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ① 枚举 + 常量（放在 FightKind 之前）
    # 锚点带上下一行（那句话在别处被引用过两次，单行不唯一）。
    ANCHOR = '''/// What the node under the cursor is waiting for.
///
/// A node is not settled by walking onto it'''
    src = patch(src, ANCHOR, ENUM + ANCHOR, 'enum')

    # ② 两个新变体
    src = patch(src, '''    /// §271：`meal_ticket` —— 进商店回 15 血。''',
                VARIANTS + '''
    /// §271：`meal_ticket` —— 进商店回 15 血。''', 'variants')

    # ③ 遗物行
    src = patch(src, '            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。',
                ROWS, 'rows')

    # ④ 两个字段
    src = patch(src, '''    /// §271：`ancient_tea_set` —— 刚进过篝火 ⇒ **下一场**战斗开战多 2 能量。
    ///
    /// 为什么是运行期字段、而不是"在篝火那一刻直接加能量"：那时没有战斗，能量无处可加
    /// （能量是战斗状态的资源）。所以只记"欠一场"，开战那一刻兑现、然后清掉。
    tea_set_pending: bool,''', FIELDS, 'fields')

    src = patch(src, '''            tea_set_pending: false,''',
                '''            tea_set_pending: false,
            unknown_room: UnknownRoom::Unresolved,
            tiny_chest_rooms: 0,''', 'field init')

    # ⑤ 掷骰 + 概率 + 访问器（放在 `unknown_odds` 旁边）
    src = patch(src, '''    /// The `?` room odds (`inv:§7.5`).
    #[must_use]
    pub const fn unknown_odds(&self) -> [i32; 3] {
        self.unknown
    }''',
                '''    /// The `?` room **miss counters** (`inv:§7.5`)：连续"没出现"的次数。
    ///
    /// §272：它们是[`Self::unknown_room_odds`]的输入，不是概率本身 —— 概率 = 基础 × (1 + 这里)。
    #[must_use]
    pub const fn unknown_odds(&self) -> [i32; 3] {
        self.unknown
    }

''' + ROLL, 'roll')

    # ⑥ `begin_node` 的 Unknown 分支
    src = patch(src, '''            NodeKind::Unknown => {
                // §271：`ssserpent_head` —— "Whenever you enter a ? room, gain 50 Gold"。
                // 走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血。
                if let Some(RelicEffect::UnknownRoomGold(amount)) =
                    self.first_relic_effect_of(RelicEffect::UnknownRoomGold(50))
                {
                    self.adjust_gold(amount);
                }
                Pending::None
            }''',
                '''            NodeKind::Unknown => {
                // §271：`ssserpent_head` —— "Whenever you enter a ? room, gain 50 Gold"。
                // 走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血。
                // wiki 的原话是 "whatever it resolves to"，所以它在掷骰**之前**付。
                if let Some(RelicEffect::UnknownRoomGold(amount)) =
                    self.first_relic_effect_of(RelicEffect::UnknownRoomGold(50))
                {
                    self.adjust_gold(amount);
                }
                // §272：`?` 房分流（wiki `Unknown Location`）。四种结果各走各的既有通道：
                //   宝箱 → `Pending::Chest`（与宝藏节点同一条路）
                //   商人 → 当场摆货架 + `Pending::Shop`（与商店节点同一条路）
                //   战斗 / 事件 → `Pending::None`，由调用方按 `unknown_room()` 决定开哪一场
                match self.roll_unknown_room()? {
                    UnknownRoom::Treasure => Pending::Chest,
                    UnknownRoom::Shop => {
                        self.stock_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }
                    UnknownRoom::Monster | UnknownRoom::Event | UnknownRoom::Unresolved => {
                        Pending::None
                    }
                }
            }''', 'unknown branch')

    # ⑦ 换幕：三条计数与 tiny_chest 计数归零
    src = patch(src, '''        // §157: the wiki resets the potion chance "at the start of each Act".
        self.potion_chance = POTION_DROP_START;''',
                '''        // §157: the wiki resets the potion chance "at the start of each Act".
        self.potion_chance = POTION_DROP_START;
        // §272：`?` 房的三条概率也换幕归零（wiki："The values for all types are reset in between
        // acts"）。⚠️ 这三条计数在 §272 之前**根本没有消费者**，所以"换幕归零"这条规则也一直
        // 没有实现 —— 现在它有了。
        self.unknown = [0; 3];
        self.tiny_chest_rooms = 0;
        self.unknown_room = UnknownRoom::Unresolved;''', 'act reset')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: ? room split + two relics')


main()
