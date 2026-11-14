"""§398 R0-2/3/4：素材流水线的三处**跨语言/分类**不一致（审阅 §3/§4/§5，全部成立）。

## ① 哈希：Python 与 JS 不是同一个 FNV-1a（审阅 §3）

Python（`build_assets.py::stable_hash`）：遍历 **UTF-8 字节**，`(value * prime) & 0xFFFFFFFF`。
JS（`registry.ts::stableHash`）：遍历 `charCodeAt`（**UTF-16 code unit**），`(value * prime) >>> 0`
—— 浮点乘法的乘积会超过 2^53，`>>> 0` 取回的低位已经不准。

审阅给的四个反例我复算过，**逐条对**：

| 输入 | 旧 JS | 正确 FNV-1a | mod 16 |
|---|---:|---:|---|
| `not_a_real_enemy` | 1294215100 | 2453344752 | 12 vs 0 |
| `new_monster_id` | 116679432 | 2615040844 | 8 vs 12 |
| `strike` | 2778783723 | 632598351 | 11 vs 15 |
| `中文` | 1362277804 | 3297308741 | 12 vs 5 |

修法：`Math.imul` + `TextEncoder().encode()`（UTF-8）—— 与 Python 逐字节一致。

## ② 调色板回退的种子不同（审阅 §3 后半）

生成器：`stable_hash(id + '|p') % PALETTES`；JS 回退：`stableHash(id) % PALETTES`。
就算哈希修好了，**同一条 id 在"清单里"与"降级时"也会落到不同调色板**。⇒ JS 也要带 `|p`。

## ③ `gremlin_nob` 被当成 Boss（审阅 §5）

生成器的 boss 名单里有 `gremlin_nob`，于是它 `scale=1.55` + `boss=true`（渲染层给它加光环）。
StS1 的 Gremlin Nob 是**精英**，不是 Boss。

修法（按审阅的建议，**把"玩法身份"与"视觉体型"分开**）：
* `boss` 只由"真的是 Boss"决定（id 含 `boss`、或 tier 是 Boss、或那张手写名单——去掉 nob）；
* 新增 `tier` 字段（`boss` / `elite` / `normal`），精英用 `scale=1.3`、**不加光环**。

## ④ 闸门的盲点：只验"覆盖"，不验"生成器变了没重跑"（审阅 §4）

`ui_assets_check.mjs` 里明写着"**不**调 `python build_assets.py --check`"（验收链 PATH 是剥空的）。
于是"生成器改了 palette/scale/boss 规则但 manifest 没重跑"这条**永远不会红**。

修法（不需要 python）：生成器把自己的**源码 sha256** 与一张**哈希对拍表**写进 `manifest.ts`；
闸门用 Node 自己算 `.py` 的 sha256 比对，并逐条验证 JS 哈希 == Python 哈希。
两条都是"陈旧生成物"的直接判据。
"""

import io
import hashlib

# ── ① JS 哈希：Math.imul + UTF-8 ──────────────────────────────────────────
PATH = 'web-next/src/assets/registry.ts'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''/** 与生成器同一条稳定哈希（FNV-1a 32 位）—— 降级时用它挑原型/调色板。 */
function stableHash(text: string): number {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index);
    value = (value * 0x01000193) >>> 0;
  }
  return value >>> 0;
}'''
NEW = '''/**
 * 与生成器**逐字节**一致的 FNV-1a 32 位（§398）。
 *
 * ⚠️ 两处都必须对，否则"清单里有的 id"与"降级时的 id"会落到不同的原型/调色板：
 * 1. **遍历 UTF-8 字节**，不是 `charCodeAt`（UTF-16 code unit）—— Python 那边是
 *    `text.encode('utf-8')`，中文/emoji 的字节数不同；
 * 2. **`Math.imul`**，不是 `value * prime >>> 0` —— 浮点乘积超过 2^53 之后低位已经不准了
 *    （审阅给的反例：`strike` 旧 JS 2778783723 / 正确 632598351）。
 *
 * 闸门 45 用生成器写进 `manifest.ts` 的**对拍表**（`HASH_FIXTURES`）逐条验证这个函数。
 */
function stableHash(text: string): number {
  let value = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    value = Math.imul(value ^ byte, 0x01000193) >>> 0;
  }
  return value >>> 0;
}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── ② 调色板回退的种子也要带 `|p` ─────────────────────────────────────────
OLD2 = '''  const paletteIndex = entry?.palette ?? stableHash(id) % PALETTES.length;'''
NEW2 = '''  // §398：种子必须与生成器一致 —— 那边是 `stable_hash(id + '|p')`。
  // 少了这个后缀，同一个 id 在"清单里"与"降级时"会落到**不同调色板**（哈希修好了也没用）。
  const paletteIndex = entry?.palette ?? stableHash(`${id}|p`) % PALETTES.length;'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('registry.ts: Math.imul + UTF-8 + |p')

# ── ③ 生成器：nob 是精英；tier 与 boss 分开；写指纹与对拍表 ────────────────
PATH2 = 'native/build_assets.py'
t2 = io.open(PATH2, encoding='utf-8').read()

OLD3 = '''    boss = ('boss' in monster_id) or (tier or '').lower() in ('boss',) or monster_id in (
        'the_guardian', 'hexaghost', 'slime_boss', 'gremlin_nob', 'the_champ',
        'bronze_automaton', 'awakened_one', 'time_eater', 'donu', 'deca', 'the_snecko',
    )
    # 体型：Boss 更大；slime 系小一号（它们是"小怪"）。
    scale = 1.0
    if boss:
        scale = 1.55
    elif monster_id.endswith('_s') or monster_id.endswith('_small'):
        scale = 0.78
    elif monster_id.endswith('_l'):
        scale = 1.2
    return {'archetype': archetype, 'palette': palette, 'scale': round(scale, 2), 'boss': boss}'''
NEW3 = '''    # §398：**玩法身份**（boss/elite/normal）与**视觉体型**（scale）分开。
    #
    # ⚠️ `gremlin_nob` 以前在这张 boss 名单里 —— 它是**精英**，于是拿了 Boss 的
    # `scale=1.55` 与光环（审阅 §5）。这类"按名字猜身份"的名单天生会漂，所以：
    #   * `boss` 只由"id 里真有 boss"或内容的 tier 决定；
    #   * 精英单独一档（放大一点，但**不**加光环）；
    #   * 想给某只怪特殊体型，写进 ENEMY_OVERRIDES，不要改身份。
    is_boss = ('boss' in monster_id) or (tier or '').lower() in ('boss',) or monster_id in (
        'the_guardian', 'hexaghost', 'the_champ',
        'bronze_automaton', 'awakened_one', 'time_eater', 'donu', 'deca', 'the_snecko',
    )
    is_elite = (tier or '').lower() in ('elite',) or monster_id in (
        'gremlin_nob', 'lagavulin', 'sentry_1', 'sentry_2', 'sentry_3',
        'book_of_stabbing', 'slavers', 'nemesis', 'reptomancer',
    )
    tier_name = 'boss' if is_boss else ('elite' if is_elite else 'normal')
    # 体型：Boss 最大、精英次之；slime 系小一号（它们是"小怪"）。
    scale = 1.0
    if is_boss:
        scale = 1.55
    elif is_elite:
        scale = 1.3
    elif monster_id.endswith('_s') or monster_id.endswith('_small'):
        scale = 0.78
    elif monster_id.endswith('_l'):
        scale = 1.2
    return {
        'archetype': archetype,
        'palette': palette,
        'scale': round(scale, 2),
        'boss': is_boss,
        'tier': tier_name,
    }'''
assert t2.count(OLD3) == 1
t2 = t2.replace(OLD3, NEW3)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('build_assets.py: nob → elite（tier 与 boss 分开）')
