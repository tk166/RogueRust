"""§276 文档 + README + 缺口文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'

DOC = """
---

## §276 容量对齐 + L 系史莱姆（含 50% 分裂）

### 276.1 先说"抬 `MAX_ENEMY_SLOTS`"这件事：**不用抬，早就是 6**

上一节说"`Swarm of Slimes` 要 5 个敌人槽，而 `MAX_ENEMY_SLOTS` 是 4" —— 核对之后发现：

| 位置 | 数值 |
|---|---|
| `rd_core::state::MAX_ENEMIES_IN_FIGHT`（内核） | **6**（§257 为 Reptomancer 的四把匕首涨的）|
| `rd_wasm::MAX_ENEMY_SLOTS`（画面/观察向量） | **6** |
| `native/sts_content_check.py` 里的**镜像** | **4** ← 只有它是旧的 |

也就是说：**能力早就有，只有闸门在原地**，于是"内核能跑"的 5 敌人遭遇被闸门挡住，而
**闸门报的是内容的错**。这是"同一个词表被两处认识就一定漂"的教科书例子。
所以这一节把镜像对齐到 6，`Swarm of Slimes` 立刻能进场。

顺带撞到第二个容量常量：`rd_core::content::MAX_POOL_IDS`（Act 1 弱池的读取上限）是 **12**，
而弱池到了 **13** —— 抬到 16（§258 的同一条理由：读取器**拒绝**而不是截断，所以它是红的而不是
"某个遭遇永远抽不到"）。

### 276.2 L 系史莱姆（wiki.gg `Slimes` + dood.gg 一致）

| 怪 | HP | A7 | 招式（base → A2） |
|---|---|---|---|
| Spike Slime (L) | 64–70 | 67–73 | Lick 2 Frail（A17: 3）；Flame Tackle 16→**18** + 2 Slimed |
| Acid Slime (L) | 65–69 | 68–72 | Corrosive Spit 11→**12** + 2 Slimed；Lick 2 Weak；Tackle 16→**18** |

AI：Spike 30% Flame Tackle / 70% Lick，不连 3 次同一招，A17 起 Lick 不连两次；
Acid 30/40/30（A17 把 Tackle 与 Lick 对调），Tackle 不连两次，其它不连三次。

**每招都维护 `last_move`/`prev_move`** —— 这是第一版漏掉的：规则读它们，却没人写，
于是"不连招"永远不触发，而**没有任何闸门会红**（加权那一条照样选出招式）。

### 276.3 分裂：阈值是一半最大血，血量是**当前血**

内核已有两条分裂，都是 **Slime Boss 专用**（固定 10 血、固定组合）：
`standard.split`（`Downed`）与 `standard.phase_split`（`DamageTaken` + 阈值 10）。
L 史莱姆要的是"**≤50% 最大血** + **继承当前血**"，所以各加一条
`standard.split_spike_l` / `standard.split_acid_l`：

```
DamageTaken:
  if currentHealth * 2 <= maxHealth:
      createCombatant(<M 型>, Health: currentHealth)
      createCombatant(<M 型>, Health: currentHealth)
      destroyCombatant(self)          # ← 必须**最后**
```

⚠️ `destroyCombatant` 一旦挪到 spawn 之前（既有的 `phase_split` 就是这么写的，因为它 spawn
常量），就退化成"分裂出两只**满血**的" —— 数量对、类型对、**只有血量错**。所以判据逐只比血量。

### 276.4 ★ 一个真 bug（§270 埋的，soak 抓到）

soak 报"死按钮"：商店里一格显示 `patient_guard+ 技能 0 金 买`，点下去
`买卡 被拒 · EmptyOffer(2)`。

根因是 §270 我给商店价格加了折扣，而折扣函数是 `(base * percent / 100).max(0)` ——
**售罄的哨兵是 `price = -1`**，被 `.max(0)` 夹成了 **0**。页面按 `price < 0` 判"已售"，
于是把卖掉的格子画成"0 金可买"。

修法：ABI 的两个价格函数**先判 `price < 0` 原样返回**，不过折扣。判据：
`rd_run_shop_*_price` 对已售格子必须回 `-1`（这是页面唯一的"已售"信号）。

这条值得记的原因：它躺在两个提交里没被发现，最后是"随机驱动点到就报"的闸门抓到的。

### 276.5 三个驱动场景的前提也写窄了

`act1_slice.mjs` 的 shop / rest / elite 三个场景用 `startTowards(name, kind, SEEDS)`，
而它只保证"地图上**能到达**该类型节点"。弱池变硬之后，第一个能到达商人的种子（101）
会在半路**被打死**（`hp 0 / Defeat`），走图停在战斗节点上，报错却是
"光标在 kind 1，期待 4（商店）" —— 看起来像路线规划器坏了。

修法：`startOn(name, kindName, seeds)` —— 选种、走过去、**验证落点**，不过就换下一个种子。
（与 §272 事件场景"按种子重试到 pending==5"同一条思路：判据的前提要从"能到"推到"走到了"。）

### 276.6 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `a_large_slime_splits_at_half_health_with_its_current_hp` | 先打 1 点（**还在一半以上 ⇒ 不许分裂**），再打到一半 ⇒ 两只 M、**血量等于那一刻的当前血**、本体消失（净 +1） |
| `a_large_slime_above_half_health_does_not_split` | 反面：擦伤不分裂 |
| `the_act_one_hard_pool_encounters_match_the_wiki_numbers`（§275 扩到 5 敌人） | `Swarm of Slimes` 的**5 个敌人**与顺序 |

**负控**（`native/p276_negative.py`，结构化改 JSON，跑完自动还原）：
① `destroyCombatant` 提到 spawn 之前（退化成满血分裂）；② 阈值改成常量 10 —— 两处全 RED ✓。

### 276.7 账

怪物 **47 → 49**；动作 **130 → 135**；状态 **124 → 126**；遭遇 **39 → 41**；
Act 1 `Weak` 池 **13 → 15**；镜像 148,032 B（core 114,304 B）；
`rd-core` **791** / `rd-run` 146 / `rd-wasm` 123；四条对拍全过；
`WEB_SMOKE` / `ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` PASS；
`COVERAGE_MATRIX` 803 行；21/21。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('/ 38 遭遇 /', '/ 41 遭遇 /')
    r = r.replace('**47 怪 /', '**49 怪 /')
    r = r.replace('（主计划 §1–§275）', '（主计划 §1–§276）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)

    gap = io.open(GAP, encoding='utf-8').read()
    old = '''| `Swarm of Slimes`（3 spike S + 2 acid S） | **第 5 个敌人槽**：`MAX_ENEMY_SLOTS = 4`，而观察向量/页面偏移/存档都按它排布 |
| Large Slime（Spike L / Acid L） | **L 系史莱姆怪物**（只有 M/S 两种） |'''
    new = '''| ~~`Swarm of Slimes`~~ | **§276 已做**：`MAX_ENEMY_SLOTS` 与内核上限**早就是 6**，卡住的只是内容门里的镜像（4）。 |
| ~~Large Slime（Spike L / Acid L）~~ | **§276 已做**：两只 L 史莱姆 + **50% 分裂**（阈值 = 一半最大血，血量继承当前血）。 |'''
    assert gap.count(old) == 1
    gap = gap.replace(old, new)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(gap)
    print('§276 doc + README + gap updated')


main()
