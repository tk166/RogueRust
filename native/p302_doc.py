"""§302/§303 文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §302 `strange_spoon`：切口在**落区**，因为那里是唯一的收敛点

`Strange Spoon`: *"Cards which Exhaust when played will instead discard 50% of the time."*

wiki 的 "Interactions" 一节把边界写得很死，而那张表正好是一张"哪些路经过出牌计划"的图：

| 情形 | 受影响 | 为什么 |
|---|---|---|
| 打出即消耗（`Offering` / `Impervious` / `Limit Break`） | **是** | 走 `plan_play` 的落区 |
| `Corruption` 让技能消耗 | **是** | 走 `corruption_destination` |
| `Havoc` / `Omniscience` **打出**的牌 | **是** | `PlayRequest::to_zone` |
| `Medical Kit` / `Blue Candle` 放行的不可打牌 | **是** | 走 `unplayable_is_free` |
| `Ethereal` 回合末消耗 | 否 | `MoveCardToZone` 请求，不经过计划 |
| 被别的效果逼着消耗（`Burning Pact` / `Fiend Fire` / `Elixir`） | 否 | 同上 |
| 不可打牌被 `Havoc` 消耗（不算"被打出"） | 否 | 被拒后放回抽牌堆顶（§241） |

所以实现不是"再加一条 50% 规则"，而是**落区那一格里掷一次骰**：`strange_spoon_destination`。

### 302.1 骰子必须在 `apply` 里掷，不能在 `plan_play` 里

`plan_play` 是**纯读**（`&CombatState`），它的存在意义是"拒绝 ⇒ 一个字节都不改"。
在计划里掷骰会让一次**被拒**的出牌也消耗随机流 —— 同一颗种子随后整场错位，而没有任何东西会红。
所以掷骰在 `apply_plan_in_chain`、**付款成功之后**（付不起的牌没被打出，不该消耗任何东西），
并且**解析一次**、两条分支（无节目 / 有节目）共用同一个答案。

### 302.2 两个副作用是**免费**的

不进消耗堆 ⇒ `Exhausted` 通知不发（wiki：与 `Feel No Pain` / `Dark Embrace` / `Dead Branch`
的反协同是写明的）；进弃牌堆也**不**发丢弃事件（wiki：*"its discard is more similar to the
automatic discarding of the player's hand"*）。两件事都不用写 —— 落区本来就是"这张牌最终去哪儿"
的唯一答案。

### 302.3 值是 wiki 的常量，开关是状态

内容那一行 `standard.strange_spoon` 是载体（`Triggers: []`，与 `medical_kit` 同形状），
遗物行用 `StartCombatStatus` 在开战时给它。内核认状态 id，百分比是常量
（`STRANGE_SPOON_PERCENT`）。

### 302.4 ★ 判据搬了一次家：`rd-core` 的测试镜像是**冻结的参考基线**

第一版把判据写在 `play.rs` 的单元层，两条都炸在 `Effect(Bind(Missing("STAT row")))` ——
因为 `content.core.rdcf` 是 `RogueDeck` 的基线（`expected_sha.txt` 钉住），**没有**我们这条状态行。
那不是遗物的问题，是"测试拿错了镜像"。

搬到 `rd-wasm` 反而**更强**：那里用的是真实 sts 镜像，链路是
**遗物 → 开战时的状态 → 落区** 完整三跳（单元层里中间那一跳断了也照样绿）。

判据：`strange_spoon_turns_about_half_of_the_exhausts_into_discards`（有遗物时两边都到过、
同种子同序列；没有遗物时**全部**消耗）、`strange_spoon_never_rolls_for_discards_or_forced_exhausts`
（弃牌与强制消耗都不掷骰 —— 直接看 `random_step`）。

---

## §303 `wing_boots`：忽略路径 = `reachable()` 里多出下一层

`Wing Boots`: *"It allows the player to select any room on the next floor when picking a Map
Location, regardless of whether it's connected to the player's current Map Location or not.
This can be done a maximum of 3 times before the relic becomes unusable."*

fandom 的描述是同一件事（*"You may ignore paths … 3 times"*）。**两份来源都没有"每幕重置"**，
所以不做重置：3 次是这一局的总次数 —— 实现"每层 3 次"要发明一条两份来源都没有的规则。

### 303.1 切口：`reachable()`，追加在**后面**

页面点房间 → `rd_run_step(index)` → `enter_node(target)`，而 `enter_node` 只认 `reachable()`
里的目标。所以"可以选下一层的任意房间" = `reachable()` 里多出那些房间。

⚠️ 追加在**最后**：与当前节点真连着的仍然排在最前面、下标不变。否则既有的页面动作号与
测试的 `reachable()[0]` 会整排位移。

### 303.2 免费 vs 飞行：`connected_nodes()` 一处出两个答案

`reachable()` 与 `enter_node()` 都需要知道"这一步是免费还是飞行"。**同一个词表两处认识就一定漂**，
所以把"真连着的那半"抽成 `connected_nodes()`，两边都调它。

* 真连着的房间（含开局第 0 层整层）：免费；
* Boss 哨兵（第 16 层）：不在"下一层的房间"里，**免费**（它只有一条路，飞过去等于白烧一次）。

### 303.3 计数进指纹与存档

`wing_boots_used` 是运行层状态：同一颗种子重放必须走同一条路，而"还能飞几次"会影响后面
**每一次** `reachable()`。所以它进 `hash`（`wb=`）与存档（`VERSION` 9 → 10）。

再拿一份 `wing_boots` **不**补次数：次数记在局上，不在每一份遗物上（wiki：*"before the relic
becomes unusable"*）。

### 303.4 判据与负控

`wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths`（rd-run）：
没有遗物时不相连的房间被拒；有遗物时整层可选且**免费的路下标不变**；飞三次每次扣一次；
用完回到普通地图；Boss 步不扣。

⚠️ 判据里"哪些是真连着的"由**地图自己重算**（`free_edges`），不能问 `reachable()` ——
拿到遗物之后它包含整层，于是每一行都会被判成"全通"（第一版就这样一路走到地图尽头）。

**负控 6 条全红**：spoon 忘读状态 / 概率 100% / 对弃牌也掷骰，boots 飞行不扣 / 免费也扣 /
用完之后还能飞。★ "Boss 步不算飞行"**不可单独失败**（Boss 在 `free` 里 ⇒ 结构上扣不到），
所以它只作为判据存在，不假装是负控。

### 303.5 页面

`rd_run_wing_boots()` 单独一个导出（观察向量是冻结的 ABI，理由同 `rd_run_girya_lifts`），
顶栏在还有次数时追加 `· 飞行 N`。没有这件遗物时那一行**逐字不变** —— 既有页面判据比的是字符串。

### 303.6 账

内容遗物 **147 → 149**（缺 46 → 44）；状态 **145 → 146**（`standard.strange_spoon`）；
镜像 167,856 B；存档 `VERSION` 9 → 10；`rd-core` 809 / `rd-run` **183** / `rd-wasm` **146**；
矩阵 875 行；八道页面门 + `SOAK`；21/21。

### 303.7 剩下的 44 件

* **E 类**：`frozen_eye`（抽牌堆显示顺序）、`runic_pyramid` 一类的手牌保留；
* **H 类**：`gambling_chip` / `toolbox`（开战前三选一）；
* **不做**：`necronomicon`（打两次）、无色池相关部分、另外三个角色、Blight。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§302 `strange_spoon`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### F.21 遗物：开局三场（§301）'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.22 遗物：落区与地图（§302/§303）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `strange_spoon` | 打出即消耗的牌 50% 改为进弃牌堆 | **已做**（发牌落区那一格掷一次骰） | 一致 |
| 边界三行 | `Ethereal` / 被效果逼着消耗 / 不可打牌被 `Havoc` 消耗 ⇒ **不**受影响 | 三者都不经过出牌计划，天然不受影响 | 一致 |
| `wing_boots` | 下一层任意房间，**3 次**，用完即失效 | **已做**（`reachable()` 追加整层 + 收费计数） | 一致 |
| 每幕是否重置 | 两份来源**都没提**重置 | 不重置（3 次是全局次数） | 写明了的解读 |

### F.21 遗物：开局三场（§301）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§301）', '（主计划 §1–§303）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
