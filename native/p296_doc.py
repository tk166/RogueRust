"""§296 文档：A3 `chemical_x`。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §296 A3：`chemical_x` —— X 费牌的 X 加 2

`Chemical X`: *"The effects of your cost X cards are increased by 2."*

### 296.1 为什么这必须是内核规则

`x.cost` 是**节目里的表达式**（`whirlwind` 的 `repeat.Count`），它读 `ExecContext::x_cost`，
而那个数在 `play.rs` 里由"这一次真的付掉多少"算出。**节目表达不了**"X 再加 2"，
所以这只能是一条内核规则 —— 与 §263 的 `the_boot` / `torii` / `tungsten_rod` 完全同族：

> 内核认这个**状态 id**，数字是 wiki 的常量，内容那一行是"载体 + 页面显示"。

`standard.chemical_x` 的内容行因此**没有修饰器、没有触发器** —— 它像 §231 的
`standard.no_draw`、§282 的 `standard.confusion`：一个**开关**，规则在 Rust 里。

### 296.2 加在 X 上，不是加在钱上

```rust
let x_bonus = if carries_status(state, &card.source, CHEMICAL_X.0) { CHEMICAL_X.1 } else { 0 };
let x_cost = x_bonus + /* 这一次真的付掉的量 */;
```

付 3 点能量、`whirlwind` 打 **5** 次。**不**动 `paid`：钱照付、`x_cost_payment` 照算，
所以"X 费牌用掉全部能量"这条规则不变。负控第 ② 条就是把加成从 `x_cost` 挪回 `paid`
—— 那会变成"多付 2 点能量"，而 X 不变。

### 296.3 与已知偏差的关系（继续成立的那条不对称）

§161.5 之后已知：**每副本价格**（`standard.card_cost_delta`）对 X 费牌**看不见** ——
X 费牌走 `x_cost_payment`（全部能量），所以"打个折"在它上面没有意义。
`chemical_x` 恰恰相反：它加的是**效果**不是**价格**，所以在 X 费牌上它是有效的。
两者不矛盾，但值得写在一起：**同一条管线上的"改价"与"改效果"是两件事**。

### 296.4 判据（两层各一条）

| 判据 | 钉住 |
|---|---|
| `chemical_x_adds_two_to_the_x_of_an_x_cost_card`（rd-core） | 3 能量 ⇒ 不带遗物 15 点（3 下）、带遗物 25 点（5 下），**差正好 10**；且 `strike`（非 X 费）仍是 6 点 |
| `chemical_x_puts_its_status_on_the_hero_at_combat_start`（rd-wasm） | 遗物 → 开战挂 `standard.chemical_x`；不带时**不挂** |

两条是**成对的**：只验内核那条，"遗物 → 状态"这一跳断了也全绿（玩家身上什么都没有）；
只验 wasm 那条，状态挂上了但没人读也全绿。

### 296.5 负控 3 条（全红）

加成恒 0 / 加成挪到 `paid` 上（钱多付、X 不变）/ 对**所有**牌都加（`strike` 6 → 8）。

### 296.6 账

内容遗物 **133 → 134**（缺 60 → 59）；状态 **132 → 133**；镜像 **164,036 B**；
`rd-core` **799**（+1）/ `rd-run` 181 / `rd-wasm` **142**（+1）；矩阵 847 行；
八道页面门 + `SOAK`；21/21。

### 296.7 A 项剩下的

| 缺的事实 | 遗物 | 说明 |
|---|---|---|
| 隐藏敌人意图 | `runic_dome` | 运行层标记 → 观测 → 页面（最小） |
| "打出的牌带某 tag 时伤害 +N" | `strike_dummy` | 伤害管线第四个改写点（与 §263 同族） |
| 每回合出牌上限 | `velvet_choker` | `plan_play` 的拒绝 + 计数器 |
| 战斗中治疗倍率 | `magic_flower` | `heal` 的数值改写（与 §263 同族） |
| `unplayable` 放行 | `medical_kit` / `blue_candle` | `validate_card_play` 的例外 |
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§296 A3：`chemical_x`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '''### F.15 遗物：打穿格挡（§295）'''
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.16 遗物：X 费牌（§296）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `chemical_x` | X 费牌的效果 +2 | **已做**（内核给 `x_cost` 加 2，内容那条状态是开关） | 一致 |
| X 的语义 | 你为这张牌付了多少 | 同一个数（**加成只加在效果里的 X**，不动付的钱） | 一致 |
| 每副本价格对 X 费牌 | 无意义（全部能量） | **仍看不见**（§161.5 的已知偏差） | 偏差（已记录） |

### F.15 遗物：打穿格挡（§295）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§295）', '（主计划 §1–§296）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
