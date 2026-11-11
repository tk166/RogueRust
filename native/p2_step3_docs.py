"""port-plan §358 + ui-p2-adapter.md + README：PendingChoice / Beat / 定向夹具。"""

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

- **卡名是定义 id**（`bash` / `strike` / `defend`）：`rd_env_card_name_*` 返回的是定义 id'''
assert t.count(anchor) == 1

addition = '''---

## §358 P2 第三步：待决选牌（`PendingChoice`）+ 演出 beat + 四条定向夹具

### ① `PendingChoice`：**十种** `kind`，一种一句

`rd_env_choice_kind` 不是三个值。它是十个（`1` 消耗 / `2` 弃掉再抽 / `3` 拿回手牌 / `4` 复制 /
`5` 升级 / `6` 放到抽牌堆顶 / `7` 拿进手牌（免费）/ `8` 放到抽牌堆底（免费）/ `9` 立刻打出 /
`10` 按印刷价格拿进手牌）。内核为每种都给**新编号**，就是因为页面要为每种写一句不同的话。

⚠️ **我的第一版只写了 0/1/2，还用 `as ChoiceKind` 强转** —— 类型检查因此没抓到。夹具真的喝了
一瓶 Attack Potion，`kind` 返回 **3** 才暴露。现在类型是十值联合 + 一张 `THEN_VERB` 表，
闸门 27 断言"十种 kind 都能写出句子、且**互不相同**"（同句 = 页面把两件事说成一件）。
未知编号落到"未知处理方式 N"，**不猜**一句像话的（猜出来的句子会静默承诺内核没答应的事）。

句子由 `(source, kind)` **两个数**决定：`kind` 说"拿进手牌"，而"从弃牌堆拿一张"与"从三个候选里
选一张"是同一个 `then` —— 所以 `source === 2` 写"从候选里选择"，`source === 1` 写"从牌堆里选择"。

**弹窗关不掉**：问句是模态的（此时动作表为空），允许关掉等于把玩家扔进"什么都点不动"的界面。

### ② 真夹具：用 Elixir 造问句

会问句的牌（`armaments` / `warcry` / `headbutt` / `exhume` / `dual_wield` / `nightmare` /
`true_grit+`）都不在起手牌里，而起手牌是随机的 ⇒ "打几把看看能不能碰到"不是夹具。
用 `rd_run_grant_potion("elixir")` + `rd_env_use_potion(0, -1)`：**一喝就问**"要消耗哪几张"。

实测：`source=1`（手牌）、`kind=1`（消耗）、`min=0 max=5`、5 个选项带标题；勾第 0 项 → 确认 →
**消耗堆 0→1、手牌 5→4**。这是真内核走完的一圈。

`rd_run_grant_potion(ptr, len)` 收的是**指针**，所以 host 加了 `writeScratch()`（往
`rd_env_scratch_buf` 写 id）—— 不猜 `__heap_base`。

### ③ 演出 beat：13 种 kind

`rd_env_beat_field(i, f)` 八个字段：kind / actor / target / flags / a / b / c / 有无定义名。
现在出牌后的提示条文案来自 beat，不再靠观察向量 diff 猜"发生了什么"。实测一次 `bash`：

```
kind 9 (cardPlayed, def=bash) → kind 1 (damage, target=0, a=8) → kind 4 (statusChanged, standard.vulnerable +2)
```

`beats_dropped > 0` 时**必须**说出来（"⚠️ 有 N 条演出被丢弃"）—— 那是降级，不能假装完整。

### ④ 四条定向夹具：三条真夹具 + 一条有理由的缺口

| 夹具 | 怎么造 | 断言 |
|---|---|---|
| **同名卡** | 起手就有 3 张 strike（两个同 `defSlot`） | 打**最后一张**（槽 4），该 `defSlot` 只少**一张**（2→1）、其它同名还在、手牌槽位压实成 `0..n-1` |
| **0 能量** | 一路出牌到能量 0 | 动作表里**没有**买不起的牌（可出性由内核 `can_play_card` 判，不是 UI 判） |
| **敌人槽位稳定** | 打到槽 0 的敌人死 | 活着的敌人**保留原槽位**（`[0,1]`→`[0,1]`，survivors `[1]`）、动作不再指向死槽、死掉的敌人**仍在向量里**（`alive=false`，槽位不塌缩） |
| **X 费扣能量** | ❌ **当前不可达** | 起手牌不含 X 费牌；药水三选一也不给（X 费牌被排除在随机候选外，扫了 seeds 1..14 的 attack_potion / skill_potion 共 28 组都没有）。只覆盖解码层（`-2 → "X"`） |

X 费那条**写进闸门输出**而不是静默跳过 —— 免得下次有人以为覆盖了。要真造它，得走奖励/商店选牌
（P3 的 run 循环），或让内核提供一个"给一张牌"的调试导出。

### ⑤ 两个"假通过"（都是我自己写的）

1. 同名卡夹具按 `card.id` 分组，而 `names()` 返回的是 `{slot, defSlot, name, text}` —— **没有 `id`**。
   于是 5 张牌全落到 `undefined`，"起手里有同名卡"这条**假通过**了。改用 `defSlot` 并加一条
   "分组键不是 undefined"的断言。
2. 分组键是**字符串**（对象键）、`card.id` 是**数字**，`===` 永远不等 ⇒ `slots` 空、`lastSlot`
   成了 `undefined`，夹具静默退化成"没测"。加 `Number()` 并断言"同名卡有多个槽位可选"。

### 数字

闸门 29 → **31**（`ui-wasm-choice`、`ui-wasm-fixtures`）；`ui-pure` 证据加 `choice=6`；
units 1233、导出 234、四条对拍不动。

### 残留

- **X 费扣能量**没有真夹具（见上）；
- **Beat 只用于提示条文案**，没有 1–13 类动画演出（plan 的 P5 才做）；
- `Copies` / `Upgrade` / `PlayChosen` 这几类问句只有句子与勾选，**没有真夹具**（当前可达路径
  只有 Elixir 的 `1:1` 与药水的 `2:3`）；
- 卡名与状态名仍是定义 id（用户已明确：与美术一起统一处理）。

### 残留

- **卡名是定义 id**（`bash` / `strike` / `defend`）：`rd_env_card_name_*` 返回的是定义 id'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    DOC,
    '''## 6. 还没做的''',
    '''## 5b. 第三步（已完成）：待决选牌 + beat + 定向夹具

`rd_env_choice_kind` 有**十个**取值（1 消耗 / 2 弃抽 / 3 拿回手牌 / 4 复制 / 5 升级 / 6 放牌堆顶 /
7 拿进手牌免费 / 8 放牌堆底免费 / 9 立刻打出 / 10 按印刷价拿进手牌）。我第一版只写了 0/1/2 还用
`as` 强转 —— 夹具真喝了一瓶 Attack Potion，`kind` 返回 3 才暴露。现在十值联合 + 一张动词表，
闸门 27 断言"十种都能写出句子且互不相同"。

**真夹具用 Elixir 造问句**（会问句的牌都不在起手牌里，随机抽不算夹具）：
`rd_run_grant_potion` + `rd_env_use_potion` ⇒ `source=1 kind=1 min=0 max=5`，勾一张确认 ⇒
**消耗堆 0→1、手牌 5→4**。

**beat** 接了 13 种 kind，出牌后的提示条文案来自内核叙述（实测 `bash`：
`cardPlayed` → `damage 8` → `statusChanged vulnerable +2`），`beats_dropped > 0` 会明说。

**定向夹具**：同名卡（打最后一张、只少一张、槽位压实）、0 能量（动作表里没有买不起的牌）、
敌人槽位稳定（`[0,1]`→`[0,1]`，死掉的敌人仍在向量里 `alive=false`）。
**X 费扣能量当前不可达**（起手牌不含、药水候选不含），只覆盖解码层 —— 这条写进闸门输出，
不静默跳过。

## 6. 还没做的''',
    'doc 5b',
)

edit(
    README,
    '''**聚合验收**：29 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm` 与 `ui-wasm-ui`），一道红就整体红''',
    '''**聚合验收**：31 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice` 与 `ui-wasm-fixtures`），一道红就整体红''',
    'readme gates',
)
print('docs updated')
