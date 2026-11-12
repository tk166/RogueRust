"""port-plan §362 + ui-p2-adapter.md + README：X 费夹具（P2 最后一条定向夹具）。"""

import io

PLAN = 'docs/port-plan.md'
DOC = 'docs/ui-p2-adapter.md'
README = 'README.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留

- **X 费扣能量**没有真夹具（见上）；'''
assert t.count(anchor) == 1

addition = '''---

## §362 X 费夹具：从奖励屏把 X 费牌弄进手牌（P2 定向夹具的最后一条）

§361 里 X 费还是"有理由的缺口"。现在补齐 —— 而且**没有靠运气**。

### 为什么不能直接拿一张 X 费牌

X 费牌（`whirlwind` / `skewer` / `malaise` / `transmutation` / `conjure_blade`）**不在起手牌**里；
`attack_potion` / `skill_potion` 的**三选一也不给**（它们被排除在"随机攻击/技能牌"候选之外 ——
扫过 14 个种子 × 2 种药水共 28 组，一个都没有）。

### 唯一确定性入口：战斗奖励屏

```
开局 → 走到战斗 → 打赢 → rd_run_fight_end()   ← 这一步才生成奖励屏（pending 4）
     → rd_run_reward_card_*() 列出候选 → 挑一张 X 费牌（rd_run_take_card）
     → 走到下一场战斗 → 结束回合直到抽到它
```

⚠️ 第一版漏了 `fight_end()`，于是 `reward_card_count()` 是 0、gold 是 0，扫了 10 个种子全是空表。
"打赢了" ≠ "奖励屏已经生成"。

扫描结果（`native/_dbg_xscan.mjs` 一次性探针）：**seed 58 的第一场奖励含 `whirlwind`**、
seed 59 含 `skewer`。所以夹具用 seed 58，确定性。

### 闸门 32 `ui-wasm-xcost`

| 断言 | 实测 |
|---|---|
| 奖励屏里确实有 X 费牌 | `["cleave","whirlwind","heavy_blade"]` |
| 手里那张的 `cost` 是 **`"X"`**（ABI 的 `-2` 正确解码，不是数字） | `{"slot":3,"cost":"X"}` |
| 出牌前有能量 | 3 |
| 打出后**能量变成 0**（X = 花光所有能量） | 3 → 0 |
| 手牌少一张 | 6 → 5 |
| 伤害至少等于花掉的能量数 | 敌人 46 → 31（3 点能量 × 5 = 15） |

证据串：`UI_WASM_XCOST PASS seed=58 card=whirlwind energy=3->0 damaged=1`

"伤害 ≥ 能量数"这条**不写死每点几点**（那是内容细节），只断言 X 的语义：花多少能量至少打几下。

### 数字

闸门 31 → **32**；units 1233、导出 234、四条对拍不动。

### 残留

- **X 费扣能量**没有真夹具（见上）；'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    DOC,
    '''## 6. 还没做的''',
    '''## 5f. X 费夹具（§362）

X 费牌不在起手牌、药水三选一也不给（扫过 28 组），唯一确定性入口是**战斗奖励屏**：

```
开局 → 打赢 → rd_run_fight_end()（这一步才生成奖励屏）→ 奖励里挑 X 费牌 → 下一场抽到它
```

⚠️ 第一版漏了 `fight_end()`，`reward_card_count()` 恒 0 —— "打赢了" ≠ "奖励屏已生成"。
**seed 58 的奖励含 `whirlwind`**，夹具确定性。

闸门 32 实测：`cost === "X"`、能量 3 → **0**、手牌 6 → 5、敌人 46 → 31（3 能量 × 5 伤害）。
证据串 `UI_WASM_XCOST PASS seed=58 card=whirlwind energy=3->0 damaged=1`。

## 6. 还没做的''',
    'doc 5f',
)

edit(
    README,
    '''**聚合验收**：31 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice` 与 `ui-wasm-fixtures`），一道红就整体红''',
    '''**聚合验收**：32 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures` 与 `ui-wasm-xcost`），一道红就整体红''',
    'readme gates',
)
print('docs updated')
