"""§272 文档 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §272 `?` 房**分流**（中资产，一次做掉）+ `tiny_chest` / `juzu_bracelet`

`begin_node` 的 Unknown 分支在 §271 之前**永远**开一个事件，而 `unknown: [i32; 3]` 那三个
计数器（在指纹里、也在存档里）**没有任何消费者**。这一节把那条规则层造出来。

### 272.1 规则（三份独立来源一致）

| 结果 | 基础 | 每次"没出现" | 出现时 | 落到 |
|---|---|---|---|---|
| Monster | 10% | +10 | 归零 | 本幕 `Weak*` 池的一场普通战斗 |
| Shop | 3% | +3 | 归零 | 当场摆货架（`Pending::Shop`） |
| Treasure | 2% | +2 | 归零 | `Pending::Chest` |
| Event | 其余（基础 85%） | —— | 不重置别人 | 调用方去开事件 |

**一次掷骰**（`RunStream::Event`）+ 前缀累加：`roll < monster` ⇒ Monster；
`< monster+shop` ⇒ Shop；`< +treasure` ⇒ Treasure；否则 Event。
换幕时三个计数归零（wiki："The values for all types are reset in between acts"）——
这条"换幕归零"以前也没实现（同样因为没有消费者），现在一起补上。

* `juzu_bracelet`：Monster 那条按成 0 ⇒ Event 变成基础的 95%（wiki 的原话是"removes the
  10% base chance … thereby increasing the base chance of Events to 95%"）。
* `tiny_chest`：**每第 4 个** `?` 房强制 Treasure（覆盖结果，不是"再掷一次"），
  同时把 treasure 计数归零。

**掷骰总是掷**：有没有这两件遗物都会消耗一次 `Event` 流 —— 与 `sozu`（不发药水但掷骰照旧）、
`white_beast_statue`（必出药水但掷骰照旧）同一条纪律：随机流的位置不随遗物变化，
否则"同一串动作"在拿遗物前后就分叉了。

### 272.2 一个结果字段，两个消费者

`begin_node` 只能返回 `NodeKind`，而"事件"与"普通战斗"都是 `NodeKind::Unknown`。所以：

* 运行层存 `unknown_room: UnknownRoom`（`Unresolved/Event/Monster/Shop/Treasure`），
  `Shop`/`Treasure` 在 `begin_node` 里**当场**变成 `Pending::Shop`/`Pending::Chest`
  （与商店/宝藏节点同一条路，不新开分支）；
* `rd-wasm` 的 `rd_run_begin_node` 只在 `Event` 时才去开事件；
* `rd_run_fight_begin` 放行 `kind == 5 && unknown_room == Monster`，用本幕的 `Weak*` 池；
* 页面靠 `rd_run_observe(18)`（**原来那一格是保留位**，长度不变）认出"这个 `?` 房是战斗"。

地图上的图标**不变**（仍是 `?`）—— 掷出来的结果不写回地图，这条判据钉在 wasm 那一层。

### 272.3 一条概率公式，两个读者

`unknown_room_odds()` 是唯一的公式（`roll_unknown_room` 也读它）。第一版把公式抄了两份，
负控的锚点当场撞出 "2 matches" —— 那正是"同一份常量抄第二份就是腐烂的开始"。

### 272.4 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_unknown_room_odds_walk_the_wikis_base_values` | 基础 `[10,3,2]`；3 次没商店 ⇒ 12、4 次 ⇒ **15**（wiki 的例子）；三条独立推进；`juzu_bracelet` 把 Monster 按成 0 而 Shop 不动 |
| `the_unknown_room_roll_matches_the_odds` | 2000 个种子：Monster ~10%、Shop ~3%、Treasure ~2%、Event ~85%（区间取得宽，因为要证的是量级） |
| `tiny_chest_and_juzu_bracelet_change_the_roll` | Tiny Chest 第 4 个 `?` 房必是宝箱且计数归零；没有它计数永远 0；Juzu 下**永不**出怪物（哪怕计数已堆到 100%） |
| `an_unknown_room_settles_into_the_channel_its_result_names` | 400 个种子里四种结果**都**要见到，且各自的 `pending`/货架对得上 |
| `an_act_change_resets_the_unknown_room_odds` | 打死 Boss 换幕 ⇒ 三个计数归零、`tiny_chest` 归零、结果回到 `Unresolved`、概率回到 `[10,3,2]` |
| `an_unknown_room_can_start_an_ordinary_fight`（wasm） | **走到**一个 `?` 房、让它自己掷出 Monster ⇒ `fight_begin` 接受；掷出 Event ⇒ 拒绝 |

**负控**（`native/p272_negative.py`）：公式去掉 `(1 + misses)`、掷骰改成 `roll % 3`、
`tiny_chest` 不覆盖结果、`fight_begin` 不放行 kind 5 —— 四处全 RED ✓。

⚠️ 负控自己也错了一次：把"掷骰"那处变异打在**公式判据**上（它不掷骰，当然还是绿的），
要点的是**分布判据**。教训与 §270 同一条：**负控没变红先怀疑负控**。

### 272.5 四条"过时的前提"被这一节暴露出来

`?` 房不再是事件之后，四条**老判据/fixture** 里写死的前提全暴露了 —— 它们不是"给新功能让路"，
而是本来就写窄了：

| 位置 | 旧前提 | 改法 |
|---|---|---|
| `an_unknown_room_opens_an_event_and_resolves_it` | `?` 房必然 `Pending::Event` | 先**找**一个真掷出事件的种子，再断言事件流程 |
| `a_recorded_run_replays…` | 按 **kind** 结算是够的 | 按 **`pending`** 结算（`pending` 才是"这个节点要什么"） |
| `rd-wasm` 的 `settle_here` / `map_test.mjs` 的 `settleHere` | 同上 | 同上，并补"`?` 房掷出怪物 ⇒ 开一场战斗" |
| `act1_slice.mjs` 的事件场景 | 走到 `?` 房就有事件，且选项一定付东西 | 按种子重试到 `pending === 5`；"付了东西"把**遗物/药水**也算进来；选项是空操作就换种子 |

最后一条还顺带修了一个**真窄**：事件付的不只是牌/血/金币，有的选项只给遗物 —— 那条断言原先
只量三样，一个合法的"给遗物"选项会被判成无操作。

`rd-wasm` 的走图助手还踩了一个自己的坑：`walk_until_unknown` 一开始**先** `mark_resolved` 再检查
类型，于是返回时那个 `?` 房已经"已结算"，`begin_node` 一路报 `NodeResolved`（1828 次走图零个结果）。
顺序反过来立刻正常。

### 272.6 没做的一件（wiki 有、我们不做）

"A `?` room right after a Merchant cannot be a Merchant" —— 这条需要"**从哪来**"，而地图只存
出边（`MapNode` 没有入边，路径也不记）。用"任一个父节点是商店"去近似会**错误地**封掉汇合点上
的商店，所以宁可写下来不做。

### 272.7 账

遗物 **105 → 107 件**；`rd-core` 788 / `rd-run` **140** / `rd-wasm` **123**；内容 124 状态 / 107 遗物；
镜像 144,820 B（core 111,492 B）；存档 `VERSION` 5 → **6**；四条对拍全过；
`ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` PASS；`COVERAGE_MATRIX` 780 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    s = io.open(README, encoding='utf-8').read()
    s = s.replace('* **遗物**：**105 / 193**', '* **遗物**：**107 / 193**')
    s = s.replace('所以缺的 88 件', '所以缺的 86 件')
    s = s.replace('/ 105 遗物 /', '/ 107 遗物 /')
    s = s.replace('144,716 B 的 `rdcf` 镜像（core 镜像 111,420 B）。',
                  '144,820 B 的 `rdcf` 镜像（core 镜像 111,492 B）。')
    s = s.replace('（主计划 §1–§271）', '（主计划 §1–§272）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(s)
    print('doc §272 + README')


main()
