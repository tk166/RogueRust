"""§301 文档：`neows_lament`（前 3 场敌人 1 血）。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §301 `neows_lament`：跨战斗的计数 + 开战时的绝对覆盖

`Neow's Lament`: *"Enemies in your first 3 combats will have 1 HP."*
一句话里有三件事，每一件都要一个不同的地方回答。

### 301.1 计数在**运行层**

"你的**前 3 场**战斗"是一个**跨战斗**的事实 —— 战斗里看不到"这是第几场"。
所以 `RunState` 多一个 `fights: u8`（`note_fight_started` 在开战那一刻 +1），
而"这一场要不要压血"由运行层回答（`enemy_health_override`）。

数的是**开始**过的战斗，不是赢过的：「前 3 场」里输掉的那一场也占一格 —— 否则输一场之后
遗物会变成"再送你三场"。

### 301.2 窗口必须**两侧**都验

```rust
if self.fights >= 1 && self.fights <= fights { Some(health) } else { None }
```

* `>= 1`：**还没开战**时不该给覆盖值（那时战斗还不存在，问题本身没有意义）；
* `<= 3`：第 4 场恢复。

第一版只写了 `<= 3`，`fights == 0` 时也返回 `Some(1)` —— 判据（"开战前是 None"）当场红。
负控又把两个边各改坏一次（去掉上界 / 窗口缩成 2），所以"窗口"这件事有三条判据守着。

### 301.3 绝对覆盖，不是百分比

`enemy_health_percent` 那条通道是给 `A7/A8/A9`（"敌人更肉"）用的**乘法**；而 wiki 说的是
"enemies **will have 1 HP**" —— 绝对值，与它们原本多少血无关。混进百分比通道会变成
"1% 血"，那是另一条规则。

### 301.4 谁写血：`rd-wasm` 的 `set_enemy_health`

装好战斗之后（与 `set_combat_hero_health` 同一个位置）：
**当前血与最大血都设 1**。只写当前血的话血条会是 `1/45`，而且任何"上限"逻辑都能把这场仗
变回去 —— wiki 的承诺是"它们**只有 1 点血**"。

与 `set_combat_hero_health` 一样**写完之后重新观察一次**：页面读的是发布出去的向量，
而它的战斗日志是两次观察的差。

### 301.5 判据与负控

| 判据 | 钉住 |
|---|---|
| `neows_lament_covers_exactly_the_first_three_fights`（rd-run） | 无遗物恒 `None`；开战前 `None`；第 1–3 场 `Some(1)`；**第 4 场 `None`**；`fights()` 计数 |
| `neows_lament_gives_the_first_three_fights_one_hp_enemies`（wasm，真开 4 场） | 前 3 场敌人 `1/1`（**血与上限都是 1**）、第 4 场有 `> 1` 的敌人 |

**负控 3 条全红**：窗口去掉上界（永远压血）/ 窗口缩成 2 场 / wasm 里不写敌人血量
（"运行层说压、战斗里没压"）。

### 301.6 ★ 这一轮踩的：wasm 判据的**驱动形状**又错了一次

第一版在循环里直接 `step → fight_begin → fight_end → step`，第 2 场 `step` 就 `-1`。
原因不是遗物：**战斗不是唯一要结算的东西** —— 奖励屏（`pending == 4`）、事件、宝箱各有
自己的收尾，而 `rd_run_step` 要求"当前节点已结算"。

修法：抄 `walk_calm_nodes` 那套动作（`step` → `begin_node` → 按种类结算 → `while pending == 4
skip_reward`）。这已经是这一系列第三次由**驱动形状**（而不是断言）导致的红
（§299 每次新建 arena ⇒ 抽到同一张、§300 手牌里只有被打的那张、本节地图没结算）。

### 301.7 账

内容遗物 **146 → 147**（缺 47 → 46）；镜像 **167,796 B**；存档 `VERSION` 8 → 9
（`fights` 进指纹与存档）；`rd-core` 809 / `rd-run` **182**（+1）/ `rd-wasm` **144**（+1）；
矩阵 872 行；八道页面门 + `SOAK`；21/21。

### 301.8 剩下的 46 件

* **E 类**（地图/页面）：`wing_boots`（忽略路径 3 次）、`frozen_eye`（抽牌堆显示顺序）；
* **F 类**：`strange_spoon`（消耗改丢弃 50%）；
* **H 类**：`gambling_chip` / `toolbox`（开战前三选一）；
* **不做**：`necronomicon`（打两次）、无色池相关的 `prismatic_shard` / `toolbox` 部分、
  另外三个角色的专属遗物、Blight（无尽模式）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§301 `neows_lament`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''### F.20 遗物：三个原子（§300）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.21 遗物：开局三场（§301）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `neows_lament` | 前 3 场战斗敌人 **1 血** | **已做**（运行层计数 + 开战时覆盖成 1/1） | 一致 |
| 计数口径 | 前 3 场（输掉也算） | 数**开始**过的战斗 | 一致 |
| 覆盖形状 | 绝对 1 血 | 当前血与**上限**都设 1（不走百分比通道） | 一致 |

### F.20 遗物：三个原子（§300）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§300）', '（主计划 §1–§301）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
