"""§192 + §193 的 plan 章节。"""
import io

PLAN = "docs/port-plan.md"

section = """
---

## 192. 把"一个动作只有一个升档档位"这个限制删掉

§190.4 写过这句话：*"`jaw_worm.bellow` 有两个阈值（Strength @A2、Block @A17），而 schema 的
单个 `ProgramAsc` 只能装一个；较早那个赢 —— 加第二个槽是格式变更，不是数据变更。"* 这一节就是
那次格式变更。

### 192.1 形状：一格 → 一格列表

```
before   "ProgramAsc": {envelope},  "AscensionMin": 2           -- 9 格 / stride 20
after    "ProgramAsc": [{"AscensionMin": 2, "Program": {envelope}}]    -- 8 格 / stride 16
```

`AscensionMin` 那一格**被删掉**，不是留着不读：两处都认识同一件事就是 §161.3 那条腐烂的老路。
选档规则写进 `Content::ascension_program`，只有一句：**`AscensionMin <= ascension` 里阈值最大的
那个**。顺序不参与判定 —— 列表是内容顺手写的，"把 A17 那条往上挪一行就换难度"这种错在任何数值
测试里都不会红（A17 的内容在 A2 下看起来只是"偏强"）。所以"升序且不重复"交给内容门单独钉。

⚠️ 一个 A17 变体是**整段节目**，所以它必须重复 A2 的改动再加自己的：
`jaw_worm.bellow` 的 A17 写的是 Strength **5** + Block **9**（wiki：`Gains (3;Asc|2|4;Asc|17|5)
Strength. Gains (6;Asc|17|9) Block.`），不是只写 Block 9。

### 192.2 代价：一份被重新钉住的镜像

`EACT` 回到 16 B（7 → 9 → 8 格），`FORMAT_VERSION` 6 → 7。roguedeck 的镜像因此缩了
87,192 → 85,616 B（394 行 × 4 B），`tools/contentc/expected_sha.txt` 必须 `--repin`。

这次重钉**是安全的**，而且判据不是"闸门绿了"：`native/card_specs.json`（四个对拍层真正读的东西）
重新生成后**逐字节不变**。原因是 roguedeck 的内容里一条 `ProgramAsc` 都没有 —— 变的只有行宽，
不是语义。重钉的注释写在 `expected_sha.txt` 里（第 2 次重钉，附理由）。

### 192.3 判据

内容门的 `INV_ASC_VARIANTS` 从 `{id: (阈值, facts)}` 变成 `{id: [(阈值, facts), …]}`，并新增四条
判断（旧表一条都说不出来）：

1. 内容里的阈值集合必须**正好**等于清单里的（多一个 = 没人钉过的档位）；
2. 阈值**严格升序且不重复**；
3. 没有两个档位和**基础节目**或**彼此**讲同一个故事（"这一档什么都不做"）；
4. `ProgramAsc` 必须是**非空列表**。

内核侧新测试 `one_action_can_carry_two_ascension_tiers` 在**两个阈值的两侧**各看一遍
（A0/A1/A2/A16/A17/A20 六行：`(3,6) (3,6) (4,6) (4,6) (5,9) (5,9)`）——
"A17 那一条忘了带 A2 的数"会红在 A17，"提前一档生效"会红在 A16。

## 193. 可变伤害：把"chosen at the start of combat"做成真的

wiki 那两句（`louse.txt:28`、`darkling.txt:32`）写的是同一件事：

> Deals N damage. N = Number between (5-7;{{Asc|2|6-8}}), **chosen at the start of combat.**

### 193.1 两个被否掉的设计，两个都值得记住

1. **在求值时抽**（`randomRange` 表达式 / `node.rollCounter` 排在 `dealDamage` 前面）。
   ⚠️ 这条会**静默打出 0 伤害**：`deal_damage_node` 在**入队时**求 `Amount`（参考的顺序），
   而计数器写入是**入队**的 `EffectRequest` —— `sequence[掷骰, 打]` 里"打"读到的是旧值。
   没有任何"发生了点什么事"的测试会红。
2. **把范围写进动作节目**（基础 + A2 两份）。那就是同一个数写两遍，而 wiki 的 A2 只是"+1"。

### 193.2 落地的形状：记录掷骰 + 参考自己的表达式

```
ENCT[i].Enemies[j].Rolls = [{Key, Min, Max, AscensionMin?}, …]      -- 每个敌人的范围
EACT[action].Program    = dealDamage{Amount: combatantCounter(source, Key)}
```

* `combatantCounter` **是参考自己的表达式**（它在 `INT_KINDS` 里），所以节目**没有**新增节点种类；
* 唯一的新东西是"谁把计数器填上"：`battle::apply_spawn_rolls`，在建战斗之后、第一回合之前，
  每抽一次 `random_step += 1`（与开局洗牌同一条"一次抽签一个步"的账）；
* 它**直接写** `set_counter`、不排队：排队就回到上面第 1 条那个 0 伤害陷阱。这是全内核唯一一处
  "求值期之外的直接写"，理由就写在这里。

`Rolls` 的阈值方向与 `ProgramAsc` **故意相反**：这里的 `AscensionMin` 缺席是"这就是基础值"，
那里的是"没填、永不生效"。所以"忘了给 A2 那行填阈值"（两行都是 0）会被当成**同键同阈值**报错，
而不是悄悄两行都生效。

### 193.3 内容门多了三道交叉检查

`INV_ROLLS` 是 wiki 数字的独立第二份（`louse_red` 5-7/6-8、`darkling` 7-11/9-13），
另外三条比数字更值钱：

1. **程序里的每个计数器读取，都必须是"列出这条动作的那个敌人"掷过的键** —— 否则两半会漂成
   "程序读 `roll.bite`、记录掷 `bite`"，伤害每一局都是 0，而两边各自看起来都对（§161.3 的形状）；
2. **读取必须来自自己**（`sel.source`），不是别人的计数器；
3. **没有敌人记录的动作不许读计数器**（`INV_UNWIRED`：`louse_green.*` 就是这种）。这条同时钉住
   "它仍然读常量"，所以"哪天把绿虱接进来"会当场红，而不是先埋一颗 0 伤害的地雷。

负控跑了五条，各红一次、各指名一件事：记录掷错键 / 读别人的键 / A2 范围改成 9-12 / 把绿虱接进
记录 / 同键同阈值两行。

### 193.4 覆盖从哪来（以及**没有**从哪来）

* **有**：`rd-core` 的 `a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action`（24 个种子 ×
  A0/A2，同一个敌人连打两次伤害**相同**且等于掷出的值，`random_step` 只涨 1；48 次掷骰至少 4 个
  不同值 ⇒ "抽签真的是抽签"）、`an_encounter_without_rolls_draws_nothing`、`rd-wasm` 的
  `building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not`（走**真入口**
  `build_session_at`，比 `random_step` 与计数器本身）、内容门的 `INV_ROLLS`。
* **没有**：`ENEMY_DIFF`。那四层对拍读的是 **roguedeck** 的 `content.core.rdcf`（394 条动作，
  `a_very_official_line.*` 之类），不是 sts 的 79 条 —— 所以 §193 的伤害数字**没有** C# 对照。
  `native/fight_diff.py` 里加了一条机械检测（`counter_draw_reason`）：如果哪天把对拍指向 sts 镜像，
  这三个动作会被明确打成 `NOT-COMPARED`（计入分母、逐行打印），而不是"两边都读 0 所以绿"。
  今天它一次都不触发 —— 因为 roguedeck 里没有一条动作读计数器。

### 193.5 数字

* **20/20 闸门绿**，单测 **840**（rd-core 663 / rd-run 107 / rd-wasm 70）。
* 镜像：sts 48,948 B（core 40,900 B）；roguedeck 158,296 B（core 85,616 B，§192 的 -1576 B）。
* 变体：**48 个动作 / 49 条**；掷骰：**2 个敌人 / 4 条范围 / 3 处计数器读取**。
* 四条对拍不变：`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、
  `ENEMY_DIFF 394/394`（不可对照 0）。
"""

src = io.open(PLAN, encoding="utf-8").read()
assert "## 192." not in src and "## 193." not in src
io.open(PLAN, "w", encoding="utf-8", newline="").write(src.rstrip("\n") + "\n" + section)
print("§192/§193 appended to port-plan")
