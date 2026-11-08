"""§305 文档：`frozen_eye`。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = r"""
---

## §305 `frozen_eye`：只改**视图**的遗物，和一个差点没生效的判据

wiki（两处独立来源一致）：*"When viewing your Draw Pile, the cards are now shown **in order**."*
Shop 稀有度。

### 305.1 页面早就有这个面板 —— 所以"没有遗物"的样子才是要写的东西

`drawBtn` → `pileEntries(0)` 一直都在，而它**永远**按 `DrawPile` 的顺序列出：等于这件遗物
一直开着。没有它时的正确样子不是"看不到牌"，而是**看到有哪些牌、看不出顺序**（StS 的抽牌堆
面板本来就是公开信息，顺序才是秘密）。

规则因此只有一句：**没有 `frozen_eye` 时按 id 排序**（确定性、不泄露顺序），并在面板上
**说明**它是排序的 —— 一个"看起来权威"的列表是更糟的失败。

### 305.2 三个落点

| 落点 | 内容 |
|---|---|
| `RelicEffect::FrozenEye` | **独立变体**，不是 `Nothing`。`Nothing` 的语义是"这件遗物什么也不做"，而这件有明确的一件事，只是发生在视图里。有它，`rd_env_frozen_eye` 问的是"这个变体在不在"，不必再抄一遍遗物 id。 |
| `rd_env_frozen_eye()` | `1`/`0`；没有局 ⇒ `0`（`rd_env` 的单场战斗没有遗物 —— 与"没有这件遗物"逐字同形，正是它该有的样子）。 |
| 页面 | `pileEntries(0)`：`!frozen_eye` 时按 id 排序 + 一行说明；牌行带 `data-card-id` 供判据读（视图上仍只显示标题）。 |

`shows_draw_order()` 是内核侧的**唯一**答案（`matches!(first_relic_effect_of(FrozenEye), …)`）。

### 305.3 判据：三层，其中一层是**同一份状态两种视图**

| 判据 | 钉住 |
|---|---|
| `frozen_eye_decides_whether_the_draw_pile_is_shown_in_order`（rd-run） | 没有遗物 ⇒ `false`；有 ⇒ `true`。两侧都验（只有"有遗物为真"的话，一条恒 `true` 的实现也全绿 —— 那正好等于遗物不存在） |
| `frozen_eye_is_a_view_flag_and_never_reorders_the_pile`（wasm） | 标志 0 → 1，而 `rd_env_pile_card_id(0, i)` 的**序列逐张不变**：排序若发生在内核里，"视图"就变成状态，之后每一次 `draw_cards` 都会按排序后的顺序发牌 |
| 浏览器（**进闸门**，`browser_test.mjs` 场景 (m)） | 同一场战斗：没有遗物 ⇒ 面板序列 = 内核序列的**排序**且**不等于**内核序列；拿遗物后 ⇒ **等于**内核序列；两边的牌数一致 |

### 305.4 ★ 这一轮踩的两次，都是"判据自己不在场"

1. **断言装在了切口下游**（FACT §4.19 的老形状）：我把 §305 的 `want(...)` 追加在文件末尾，
   而 `if (problems.length) fail(...)` 在那之前 —— 于是那几条断言**从来没跑过**，
   而闸门照样 PASS。发现它的是"日志里 `flag 0 -> 0` 却判绿"这个**矛盾**，不是断言本身。
   ⇒ 断言的位置也是判据的一部分。
2. **内容没重建**：遗物行写进了 JSON，但镜像没重编，`rd_run_grant_relic` 正确地说
   "`frozen_eye` 不是内容的 REL 行"（-2）—— 而页面上的表现只是"遗物没生效"。
   同一个形状在 §304 也出现过（`standard.strange_spoon`）；**改 JSON 之后必须重编并看门**。

另外两次是纯粹的 `browser_test.mjs` 模板串坑（反引号），与 FACT §2b 一字不差：注入块里
**不写反引号**。第一次让我看到 `SyntaxError`，第二次是同一处注释又写了一个。

### 305.5 账

内容遗物 **151 → 152**（缺 42 → 41）；镜像 167,956 → **168,008 B**；`rd-core` 809 /
`rd-run` **185**（+1）/ `rd-wasm` **150**（+1）；矩阵 878 行；八道页面门 + `SOAK`；21/21。
浏览器闸门从"读了没断言"变成"两条负控都能红"：**2 条负控全红**。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§305 `frozen_eye`' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(
            plan.rstrip('\n') + '\n' + DOC)

    g = io.open(GAP, encoding='utf-8').read()
    marker = '### F.23 遗物：开战问一句（§304）'
    assert g.count(marker) == 1
    g = g.replace(marker, '''### F.24 遗物：只改视图（§305）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `frozen_eye` | *"When viewing your Draw Pile, the cards are now shown in order"* | **已做**：没有遗物时面板按 id **排序**并说明；有遗物时就是内核顺序 | 一致 |
| 面板显示什么 | 有哪些牌（公开信息），不是顺序（秘密） | 排序视图只显示标题 + 一行说明 | 一致 |
| 是否改状态 | 不改 | 抽牌堆序列逐张不变（判据 + 负控钉住） | 一致 |

### F.23 遗物：开战问一句（§304）''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§304）', '（主计划 §1–§305）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('docs written')


main()
