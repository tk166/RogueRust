"""port-plan §359 + ui-p2-adapter.md + README：中文映射表。"""

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

## §359 中文映射表：内容 id → 显示名/介绍

内核只给**定义 id**（`rd_env_card_name_*` 返回 `strike` / `strike+`），本地化是展示层的事。
一张表把它隔开：内核不用知道中文，UI 不用知道 ABI。

### 数据来源（两个，互相核对）

| 来源 | 用途 | 结果 |
|---|---|---|
| **spire-archive**（`spire-archive.com/api/sts1`，从游戏文件解析、13 语言） | **主来源**（机器可读、可复现） | 卡牌 267/295、遗物 138/152、药水 30/33、怪物 46/61 |
| 仓库自己的 `sts/content/*.json`（早先里程碑的中文） | **交叉核对** | 两边都有的 id 里 **8 处不一致** |

⚠️ 那 8 处是仓库里的旧中文**缩写**：`iron_wave` 仓库写"铁斩"、官方是"铁斩波"；`cleave` 顺劈/顺劈斩；
`pommel_strike` 柄击/剑柄打击；`inflame` 燃心/燃烧；`shrug_it_off` 耸肩/耸肩无视；
`jaw_worm` 颚虫/大颚虫；`oddly_smooth_stone` 光滑的石头/意外光滑的石头；`blood_vial` 血瓶/小血瓶。

**灰机中文 wiki（`sts.huijiwiki.com`）被 Cloudflare 挡**（`urllib` 与 API 端点都 403），只能靠
`web_search` 的 snippet 逐条取。抽查过两条：`铁斩波` = Iron Wave、`打击` = Strike —— **wiki 站在
spire-archive 一边**，所以采用官方名。

### 回退链（三层，每层都显式）

1. 精确命中；
2. `strike+` / `searing_blow+++` → **剥掉所有** `+` 查基础条目，名字补回 `+`；
3. 都没有 ⇒ 返回**定义 id 本身**（`insight` / `standard.ritual`）并**计数**。

第 3 层为什么重要：静默回退到英文会让"没翻译"看起来像"翻译成了英文"。`coverage()` 把回退
次数暴露出来，闸门 29 断言"这一局里回退数 = 0"、闸门 27 断言"回退被计数"。

### 已知不精确（都写进代码注释与闸门输出）

- **`+` 变体的介绍沿用基础文本**（126 条）：spire-archive 的 `upgrade.description` **只有英文**，
  中文升级描述不在它的数据里。名字有 `+`、数值文本是基础的 —— 显示层不精确，但**不假装**。
- **28 张卡没有中文**：`insight` / `miracle` / `omega` / `shiv` / `smite` / `beta` / `j.a.x.` /
  `expunger` / `through_violence` / `patient_guard` 这些**特殊/衍生牌**不在 spire-archive 的表里。
  它们回退成 id。
- **状态 13/150**：spire-archive 的 `powers` 端点**只给英文**（试过 `zh`/`zhs`/`zh-CN`/`cn`），
  所以状态名用仓库自己的中文（ABI 五轴 力量/易伤/虚弱/敏捷/脆弱 + 荆棘/仪式/金属化等）。
- **卡牌"种类"（配色）仍是猜的**：观察向量里没有种类，按规则文本里有 `damage` 或 `伤害` 判攻击牌。

### 落地

- `native/build_zh_i18n.py` → `web-next/src/i18n/zh.ts`（**生成物**，不手改）；
  原文缓存在 `native/zh_source/`（**入库**）⇒ 闸门不联网；`--refresh` 才重抓。
- `web-next/src/i18n/index.ts`：`displayName` / `displayText` / `coverage` / `resetCoverage`。
- 接进 `viewFromWasm`（手牌名+规则、敌人名）与 `beatText`（`cardPlayed` 的卡名、状态名）。

### 两个"中文一来就坏"的地方

1. 闸门里"找一张会打人的牌"用 `/damage/i` 匹配**视图规则文本** —— 文本变中文后永远不匹配
   （闸门 29 立刻红）。改成 `damage|伤害`。闸门 28 用的是**内核文本**（仍英文），保持不变。
2. `guessKind` 按 `damage` 判攻击牌 ⇒ 中文文本下所有牌都变"技能"（截图上一手牌同色）。
   同样改成中英双匹配。

### 数字

闸门 31 不变；`ui-pure` 证据加 `i18n=7`；`ui-wasm-ui` 加两条断言（手牌名全是中文、本局回退数 0）；
映射表 494 条（卡 267 / 遗物 138 / 药水 30 / 怪 46 / 状态 13）；units 1233、导出 234、四条对拍不动。

### 残留

- **X 费扣能量**没有真夹具（见上）；'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

edit(
    DOC,
    '''## 6. 还没做的''',
    '''## 5c. 中文映射表（§359）

`native/build_zh_i18n.py` 生成 `web-next/src/i18n/zh.ts`：内容 id → 中文名/介绍，494 条
（卡 267 / 遗物 138 / 药水 30 / 怪 46 / 状态 13）。

主来源是 **spire-archive**（从游戏文件解析的 13 语言库，`/api/sts1/...`）；仓库自己的
`sts/content/*.json` 用来**交叉核对**，两边有 8 处不一致 —— 都是仓库里的旧中文缩写
（`iron_wave` 铁斩 vs 官方铁斩波、`cleave` 顺劈 vs 顺劈斩…）。灰机中文 wiki 被 Cloudflare 挡，
只能靠 search snippet 抽查：`铁斩波` = Iron Wave 与 `打击` = Strike 都**站在 spire-archive 一边**，
所以采用官方名。

回退链三层：精确 → 剥掉所有 `+` 查基础（名字补回 `+`）→ **返回 id 本身并计数**。
第三层是为了让"没翻译"看得出来：静默回退成英文会假装翻译过。闸门 29 断言"这一局回退数 = 0"。

已知不精确：`+` 变体的介绍沿用基础文本（126 条，来源只给英文升级描述）；28 张特殊/衍生牌
（`insight` / `shiv` / `omega` …）不在来源里；状态 13/150（`powers` 端点只给英文）。

## 6. 还没做的''',
    'doc 5c',
)
print('docs updated')
