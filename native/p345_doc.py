"""§345 文档：**内核给 id、显示层给名字** 这条原则 + G4/G5/G8 的重新定性。"""

import io

DOC = 'docs/ui-state-model.md'
PLAN = 'docs/port-plan.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① §0.5 新原则 ─────────────────────────────────────────────────────────
t = io.open(DOC, encoding='utf-8').read()

t = sub(t, '''---

## 1. 场景总表''',
        '''### 0.5 内核给 **id**，显示层给**名字**（§345）

这是一条**接口原则**，不是实现细节：

> 最终需要的效果是 **UI 显示的名字和内核的名字可以不一样**（规避版权等用途、本地化、以及纯粹的
> 品味），通过**映射表**实现 —— 所以 ABI 一律给 **id** 是好事。

| 层 | 职责 |
|---|---|
| 内核 / ABI | **只给 id**（`entropic_brew`、`slime_boss`、`defend+`、`standard.constricted`） |
| 显示层（`web/ui_render.js`） | `displayName(id, kernelName)` = **替换表 → 内核/内容名 → 美化 id** |

三条推论：

1. **改名不该动内核**。一旦把 "Slime Boss" 写进 ABI，改名的成本就从"改一张表"变成
   "改内容 + 重编镜像 + 重跑四条对拍"。
2. **同一个内核要能喂两套名字**（正式版 / 试玩版 / 不同语言），所以映射表必须能**覆盖**
   内核给的名字 —— 这条优先级是"规避版权"能不能做到的分界，判据钉的就是它。
3. **判据要查 id，不查名字**。浏览器判据原来按"面板文本的第一个词"认敌人，页面一印显示名
   （"Bronze Orb"）就分不清谁是谁 ⇒ 面板改成带 `data-enemy-id`，判据查 id（这比原来更准）。

> 于是 G4 / G8 的定性要改：它们**不是"缺导出"** —— 药水 id 与商店四排 id 早就在，缺的是
> 显示层的映射。真正的缺口只有 G5（Boss 连 id 都没有）。

---

## 1. 场景总表''', 'section 0.5')

# ── ② §6 缺口表：G4/G5/G8 重新定性 ────────────────────────────────────────
t = sub(t, '''| **G4** | **药水没有显示名/描述** | 只显示 id（`entropic_brew`） | `rd_run_potion_name_len/into`、`..._text_...` | 小：`POT` 段已有字段 |''',
        '''| ~~**G4**~~ | ~~药水没有显示名~~ | — | **已关闭（§345）**：**不需要新导出** —— `rd_run_potion_id_*` 早就在，缺的是显示层。`displayName()` 把 `entropic_brew` 念成 "Entropic Brew"，要改名就进 `NAMES` 表 | 已完成（架构原则见 §0.5） |''',
        'G4 closed')

t = sub(t, '''| **G5** | **Boss 名字写死** | `snapshot.bossName = "Slime Boss"` | `R.txt(boss_name)` 或从 `ENCT` 读 | 小 |''',
        '''| ~~**G5**~~ | ~~Boss 名字写死~~ | — | **已关闭（§345）**：`rd_run_boss_id_len/into` → 本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …），显示层决定怎么念 | 已完成。这是唯一真缺的导出（内核连 id 都没给） |''',
        'G5 closed')

t = sub(t, '''| **G8** | **商店四排都没有标题** | 回退到 id | 与 G4 同一个形状：`shop_*_title_len/into` | 小 |''',
        '''| ~~**G8**~~ | ~~商店四排都没有标题~~ | — | **已关闭（§345）**：同 G4 —— 四排 id 早就在，显示层负责名字 | 已完成 |''',
        'G8 closed')

# ── ③ §2.1 顶栏：Boss 名与遗物 chip 的来源 ───────────────────────────────
t = sub(t, '''| `contentPin` | 8 位十六进制 | 构建时定死 | `rd_content_fingerprint()` | T0 | 与 `packages/sts/out/build.json` 的镜像 sha 同源 |''',
        '''| `contentPin` | 8 位十六进制 | 构建时定死 | `rd_content_fingerprint()` | T0 | 与 `packages/sts/out/build.json` 的镜像 sha 同源 |
| `bossId` | 敌人 id（`slime_boss` / …） | 换幕 | `R.txt(boss_id)` | T1 | §345：**给 id**，屏幕上的名字由 `displayName()` 决定（原来是写死的 `"Slime Boss"`） |''',
        'boss id row')
io.open(DOC, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ port-plan §345 ─────────────────────────────────────────────────────
SECTION = """
## §345 内核给 id、显示层给名字 —— 以及"能用的一版"

用户在这一轮给了一条**架构方向**：

> 最终需要的效果是 UI 显示的名字和内核的名字可以不一样（规避版权等用途，通过映射表实现），
> 所以接口是 id 可能是好事。

这句话把剩下的三个"名字缺口"重新定性了，也让这一节的改动量缩小了一半。

### 重新定性：G4 / G8 不是"缺导出"

| 缺口 | 原来的定性 | 实际 |
|---|---|---|
| G4 药水没有显示名 | "缺导出" | `rd_run_potion_id_*` 早就在 —— 缺的是**显示层** |
| G8 商店四排没有标题 | "缺导出" | 四排 id 早就在 —— 同上 |
| G5 Boss 名写死 | "缺导出" | **真缺**：内核连 Boss 的 id 都没给 |

⇒ 这一节只加**一个**导出（Boss 的敌人 id），其余全在显示层。

### 显示层：`displayName(id, kernelName)`

```
displayName(id, kernelName) =
    NAMES[id]        // ① 替换表：版权改名、本地化、任何"屏幕上的名字"
 ?? kernelName       // ② 内核/内容给的名字（遗物的 DisplayName、卡的 NameKey）
 ?? prettifyId(id)   // ③ 兜底：`entropic_brew` -> `Entropic Brew`
```

**① 必须能覆盖 ②** —— 这是"规避版权"能不能做到的分界。判据里专门有一条把它钉住
（临时往 `NAMES` 插一条 `slime_boss`，断言它赢过内核名）。

`prettifyId` 的五条规则：`_` 分词首字母大写、单字母词整体大写（`acid_slime_m` → `Acid Slime M`）、
`+` 是升级标记属于后缀（`defend+` → `Defend+`）、去掉内容命名空间（`standard.constricted` →
`Constricted`）、空就是空（不编名字）。

`NAMES` **空表是正常状态**：美化规则已经够用；要改名就往里加一行 —— 加在这里而不是内核里，
因为**同一个内核要能喂两套名字**。

### 页面接线

| 位置 | 之前 | 现在 |
|---|---|---|
| 药水腰带 | `entropic_brew` | "Entropic Brew" |
| 商店四排 | id（`title` 是空串 ⇒ 面板回退到 id） | 显示名 |
| 遗物 chip | 内核 `DisplayName` | `NAMES` 优先，回退内核名 |
| 敌人面板 | id（`acid_slime_m`） | 显示名 + `data-enemy-id`（判据查 id） |
| Boss 标题 | **写死** `"Slime Boss"` | `rd_run_boss_id_*` → 显示层（第二、三幕不再显示错的 Boss） |

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `ui_test.mjs` 的 `display names` 段 | `prettifyId` 五条规则 + **优先级**（替换表 > 内核名 > 美化 id）+ 替换表真的能覆盖内核名 |
| `the_boss_id_follows_the_act`（rd-wasm） | 三幕的 Boss id **互不相同**（只断言"非空"的话，永远返回第一幕的实现也会绿 —— 那正是写死的等价物） |

负控 **4/4**（`native/p345_negative.py`）：`prettifyId` 丢 `+` 后缀 / 不去命名空间 /
`displayName` 优先级反过来 / Boss id 永远返回第一幕。

### 顺手修的一处判据（不是顺手，是必须）

浏览器判据原来按"敌人面板文本的第一个词"认名字。页面开始印显示名之后，Boss 是
"Bronze Automaton"、两个球是 "Bronze Orb"，**第一个词都是 "Bronze"** ⇒ 判据报
`got ["Bronze","Bronze","Bronze"]`。

修法不是改期望值，而是给面板加 `data-enemy-id`、判据改查 **id** —— 这比原来**更准**
（验的是"这一格确实有身份"，而不是"第一个词长什么样"），也正是 §0.5 那条原则想要的性质。

### 数字

`rd-wasm 188`（187 + 1）、`rd-run 225`、`rd-core 819`、units **1232**（下限 1231 → 1232）；
导出 224 → **226**；四条对拍不动；`WEB_SMOKE PASS` / `UI_RENDER PASS` / `BROWSER_TEST PASS`；23/23 闸门。
"""

p = io.open(PLAN, encoding='utf-8').read()
assert '## §345' not in p
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(p.rstrip('\n') + '\n' + SECTION)
print('ui-state-model §0.5 + G4/G5/G8 closed ; port-plan §345')
