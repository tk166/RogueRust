"""§384 的文档。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = '''

---

## §384 选牌弹窗（武装 / 头击）显示英文名

玩家报的：

> "战斗界面的武装、头击等牌需要选择已有手牌的时候，弹出窗口显示的是牌的英文名非常不直观，
> 可以改成和商店与奖励一样的二维绘图 + 映射表中文名 + 悬浮提示。"

### 384.1 根因

`ChoiceModal` 渲染的是 `option.title`，而它是内核的 `rd_env_pile_card_title_*`
—— 内容是 `CARD.NameKey`（**英文**：`Strike+` / `Defend`）。中文在 i18n 的 `cards` 表里。
商店/奖励屏早就改成 `displayName("cards", id)` 了，只有这一屏漏了（组件里那行注释还写着
"本地化与卡名一起处理" —— 那是**许诺**，不是实现）。

### 384.2 修法：先把文案抽成纯函数，再让组件只做渲染

| 层 | 文件 | 职责 |
|---|---|---|
| 纯文案 | `view/cardTipText.ts`（新） | `describeTip`：名字 / 种类·费用·稀有度 / 正文 |
| 纯文案 | `view/choiceText.ts` | `choiceOptionLabel`：选牌弹窗一行的 `{name, subtitle}` |
| 渲染壳 | `run/overlays/CardTip.tsx` | 固定面板（`position: fixed`，§381） |
| 渲染壳 | `overlay/ChoiceModal.tsx` | 勾选 + `Badge` 二维卡面 + 中文名 + 副标题 + 悬浮详情 |

**为什么要把 `describeTip` 从 `.tsx` 搬到 `view/cardTipText.ts`**：`choiceText.ts` 是闸门 27
直接编译成 ESM 跑的文件，而那一趟 tsc **没有 jsx 支持** ⇒ 它一旦 import `.tsx`，整条编译链
就崩（实测 `ERR_MODULE_NOT_FOUND ... CardTip.js`）。分层本来也该这样：文案可被纯函数闸门穷尽
断言，DOM 只留渲染壳。

### 384.3 回退顺序只有两层

i18n 中文 → **美化 id**（`patient_guard` → `patient guard`）。

⚠️ **故意不用内核的 `option.title`**：它的信息量与"美化 id"完全一样（都是英文），
而英文名在一屏中文里最扎眼。参数留着（调用方手里本来就有），但不读。

### 384.4 判据（闸门 56 里新增 6 条）

1. 白名单之外**每一张**牌都显示中文名（穷尽遍历内容里 295 张）；
2. 没翻译的牌显示**美化 id**，不是机器码（`patient_guard` 不许原样印出来）；
3. 没翻译的牌**只有白名单那 15 个 id**（14 张观者/特殊牌 + `j.a.x.`）——
   新增一张没翻译的牌会让这条红，而不是静默变回英文；
4. `ChoiceModal` 真的调了 `choiceOptionLabel`（纯函数测了但没人调等于没修）；
5. `ChoiceModal` 不再直接印 `option.title`；
6. `ChoiceModal` 有 `badgeLook("cards")` 与 `<CardTip>`；
7. 副标题带**费用**（与商店/奖励的悬浮面板**同一个来源**）。

### 384.5 那 15 个没翻译的 id

`patient_guard` / `insight` / `miracle` / `omega` / `expunger` / `shiv` / `smite` / `beta` /
`through_violence` / `jax` / `j.a.x.` / `safety` / `become_almighty` / `live_forever` /
`fame_and_fortune`

全是**观者 / 特殊牌**：本移植是 Ironclad 口径，它们拿不到（内容包里有，因为内容包是全角色的）。
所以它们**不会**出现在一局真正的选牌弹窗里；万一出现，显示的是美化后的英文 id。

### 384.6 还欠的

* 这 15 张牌没有官方中文条目（`zh.ts` 里 `jax` 甚至有键但名字是英文 `J.A.X.`）——
  要补得先在 spire-archive 的 zh 表里对上 id；
* 选牌弹窗的卡面是 `size="sm"` 的徽章（两位字母），不是插画（与全仓库同一条现状：
  只有程序化几何，没有 GLB 资产）；
* 弹窗里没有"这张牌升级后会变成什么"的提示 —— `Armaments` 选牌时那其实是最需要的信息。
'''

PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §384' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + SECTION)

edit(
    'README.md',
    '> **卡牌详情**：奖励屏/商店里把鼠标移到牌上（触屏是按住）就显示 种类 · 费用 · 稀有度 · 规则。',
    '> **卡牌详情**：奖励屏/商店/**战斗中的选牌弹窗**（武装、头击…）里把鼠标移到牌上（触屏是按住）\n> 就显示 种类 · 费用 · 稀有度 · 规则；选牌弹窗里每张牌都是"二维卡面 + 中文名"。',
    'readme tip',
)
print('docs written')
