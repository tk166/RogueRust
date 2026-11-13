"""§370 幕间文档：port-plan + README + ui-parity。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §370' not in t
section = '''

---

## §370 幕间：幕数显示 + 幕通关屏 + Boss 遗物三选一

三件事一起做，因为它们在 StS 里是**同一个时刻**：打赢 Boss → 回满血 → 三选一 Boss 遗物 →
下一幕。前两件是 UI，第三件要动内核。

### 370.1 幕数显示（UI）

**问题**：换幕后 `floor` 归 0，而 UI 只画层数 ⇒ 地图页显示 **"第 0 层"**，玩家以为回到开头。
`act` **不在** 19 格观察向量里，只能从 `rd_run_act()` 单独读。

**修法**：`RunState.act`（来自 `rd_run_act()`）+ 顶栏"第 N 幕" + 地图标题"第 N 幕 · 第 M 层"。
没开局时 `act == 0` ⇒ 显示"—"（不是"第 0 幕"）。

### 370.2 幕通关屏 = Boss 遗物三选一（`SC-13`）

内核的 `mark_boss_beaten` 已经做了"回满血 + 换幕 + 按 `act_seed()` 生成新地图"，
缺的是 StS 的最后一步：**三选一**。所以这一屏同时承担"这一幕通关"的叙事与"必须选一件"的动作
（分开成两屏会让玩家在两屏之间没事可做）。

**为什么与 `Pending` 分开**：打赢 Boss 的那一步会**先**掷奖励屏（`Pending::Reward`），
三选一是奖励屏关掉**之后**才该出现的 —— 塞进 `pending` 会把奖励屏顶掉（§329 记过同类顺序问题）。
所以它是一组独立查询，场景规则是"`boss_relic_count > 0` ⇒ `SC-13`"，排在奖励之后、地图之前
（闸门 33 断言 `8 < 9 < 16`）。

### 370.3 内核改动（`rd-run` / `rd-wasm`）

| 项 | 内容 |
|---|---|
| 状态 | `boss_relic_offer[3]` + `boss_relic_offer_len` |
| 生成 | `offer_boss_relics(relic_pool)`：只含 `Rarity::Boss`、排除已持有、均匀抽 3 件互不重复 |
| 取走 | `take_boss_relic(slot, card_pool)`：越界 `EmptyOffer(slot)`、没有待选 `WrongPhase` |
| 指纹 | 加 `boss_relic_offer_len=` + 每件一行 |
| 档案 | `VERSION 13 → 14`（否则回档丢"我还欠你一个三选一"） |
| ABI | `rd_run_boss_relic_count/_id_len/_id_into/_take_boss_relic` + 夹具 `rd_run_offer_boss_relics` |

⚠️ **不能走 `pick_relic`**：它把 `Boss`/`Shop`/`Event` 当"不可掉落档位"过滤掉（不在
`RELIC_RARITY_WEIGHTS` 里），于是三选一会安静地变成"没得选"。所以自己抽（均匀，不按权重）。

### 370.4 顺带修掉日志种类表的三个既有 bug

`rd-wasm` 的回放脚本用 `K_*` 常量标动作，表里原来有三处错：

1. **`K_END_ACT` 与 `K_GRANT_POTION` 都是 21** ⇒ `match` 先出现的胜出，`end_act` 的回放实际
   调用 `grant_potion("")`，幕尽那一位永远不生效（回放会分叉）。调试钩子挪到 `0x5f`。
2. `K_PICKUP_ADD_CARD` 等五行在 `rec_kind_name` 里**重复了一遍**（unreachable pattern）。
3. `K_BUY_COLORLESS` / `K_BUY_POTION`（§332）**没有名字** ⇒ 脚本里写 `?`，回放读不回来。

### 370.5 判据

| 层 | 判据 |
|---|---|
| 内核 | `cargo test -p rd-run boss_relic`：只从 Boss 池且排除已持有 / 越界与空池 / 档案往返 |
| 场景 | 闸门 33：`SC-13` 逐行夹具 + 顺序 `reward < bossRelic < map` |
| ABI | 闸门 47：正式路径**没有**夹具入口；`?debug` 下三选一三件都来自内容的 Boss 档、互不重复 |
| 端到端 | 闸门 47：拿走进腰带、这一手清空、场景**自动**回地图、没有待选时再取被拒且腰带不变 |

⚠️ **E2E 用 `?debug` 夹具造 offer**：三选一是换幕时由内核生成的，而"打赢一场 Boss"没法按需
制造（自动出牌策略打不过第 16 层）。夹具走的是**同一个** `offer_boss_relics`，只是触发时机由
闸门决定 —— 与 `rd_run_grant_potion` 同一条纪律。

### 370.6 数字

闸门 46 → **47**；units 1233 → **1236**（+3 条内核判据）；导出 234 → **239**；
wasm 1,371,732 B；`coverage-matrix` 重生成（rows=957, tests=1238）。

### 370.7 还欠的

* 三选一的 **E2E 只有夹具触发**，真路径要打赢 Boss（同 §365.4 的欠账）；
* 幕间没有"幕布"演出（`ui-state-model.md` §2.3 记的 `#actCurtain`），现在只有一屏静态文字；
* `SC-12a`（幕通关）仍然不可达：换幕在 `mark_boss_beaten` 里**立刻**发生，没有"停在幕末"的相位。
'''
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

edit('README.md', '**聚合验收**：46 道闸门', '**聚合验收**：47 道闸门', 'readme count')
edit(
    'README.md',
    '''* **幕间没有节奏**：打赢 Boss 后静默换幕（`act+=1`、`floor=0`、新地图），但 UI **不显示幕数**、
  地图页会显示"第 0 层"，**没有 Boss 遗物三选一**（内核无 `boss_relic`）。''',
    '''* **幕间**（§370 已补）：幕数显示（顶栏 + 地图标题）+ **Boss 遗物三选一**（内核
  `offer_boss_relics` / `take_boss_relic`，`SC-13`）。仍欠：真路径 E2E（要打赢 Boss）与幕布演出。''',
    'readme act',
)

edit(
    'docs/ui-parity.md',
    '''| **SC-12a/b** 幕通关/局终 | 有 | `EndScene` | 对等 |''',
    '''| **SC-12a/b** 幕通关/局终 | 有 | `EndScene` | 对等（`SC-12a` 仍不可达：换幕立刻发生） |
| **SC-13** 幕间·Boss 遗物（§370） | 无（旧入口只换幕，不给 Boss 遗物） | `BossRelicScene` | **新入口更好** |''',
    'parity act',
)
print('docs written')
