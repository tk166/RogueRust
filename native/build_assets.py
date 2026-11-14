"""素材清单生成器：内容 id → 素材描述（`web-next/src/assets/manifest.ts`）。

## 这一层解决什么

"每个敌人/卡牌/遗物/药水/状态都要有东西可画"这件事，如果靠**手写一张表**，那么
"内容加了 30 张牌而美术没跟上"就永远只能靠人发现。所以：

1. 清单从**内容镜像**（`tools/contentc/packages/sts/sts.roguedeck.json`）**穷尽**枚举 id；
2. 每个 id 的描述由**确定性规则**给（稳定哈希 → 调色板/原型），所以**没有洞**；
3. 少数 id 有手写覆盖（`strike` 该是红的、`slime_boss` 该是大的），但**覆盖是可选的**，
   不是覆盖才有素材。

## 二维/三维的分工（这一版）

* **三维敌人**：16 种「立体几何排列组合」原型（`assets/geometry.ts` 里的纯数据），
  每个原型由 2–6 个基本体（球/盒/锥/柱/环/八面体/胶囊）摆出来。清单只记**原型名 + 调色板**。
* **二维元素**（卡面/遗物/药水/状态）：**两位大写字母** + 调色板。字母由 id 规则生成
  （`twin_strike` → `TS`，`strike` → `ST`，`standard.vulnerable` → `SV`）。

## 用法

    python native/build_assets.py            # 重新生成（内容变了就跑）
    python native/build_assets.py --check    # 只校验清单是否与内容一致（闸门 45 用）
"""

import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, 'tools', 'contentc', 'packages', 'sts', 'sts.roguedeck.json')
OUT = os.path.join(ROOT, 'web-next', 'src', 'assets', 'manifest.ts')
NL = chr(10)

# ── 调色板（8 组；`body`/`accent`/`eye` 三个角色）──────────────────────────
PALETTES = [
    {'name': 'ember', 'body': '#c0503f', 'accent': '#f0a13a', 'eye': '#ffe9c9'},
    {'name': 'frost', 'body': '#3f7cc0', 'accent': '#7fd0f0', 'eye': '#e8f7ff'},
    {'name': 'venom', 'body': '#5f9f4a', 'accent': '#b8e06a', 'eye': '#f2ffd9'},
    {'name': 'void', 'body': '#6b4a9f', 'accent': '#b28ae0', 'eye': '#f0e6ff'},
    {'name': 'rust', 'body': '#8a5a2b', 'accent': '#d8a24a', 'eye': '#fff2dc'},
    {'name': 'bone', 'body': '#9aa7b8', 'accent': '#e6edf3', 'eye': '#2b3440'},
    {'name': 'blood', 'body': '#8f2f3a', 'accent': '#e0606b', 'eye': '#ffe0e2'},
    {'name': 'jade', 'body': '#2f8f7a', 'accent': '#6fe0c0', 'eye': '#e0fff8'},
]

# ── 三维原型（名字必须与 `assets/geometry.ts` 的目录一致；闸门 45 会核对）────
ARCHETYPES = [
    'slime', 'humanoid', 'beast', 'construct', 'gremlin', 'slaver', 'louse', 'sentinel',
    'spire_guard', 'floating_orb', 'plant', 'crystal', 'boss_blob', 'boss_machine', 'worm', 'ghost',
]

# 手写覆盖：**可选**的偏好（没覆盖的走确定性规则）。
ENEMY_OVERRIDES = {
    'cultist': ('humanoid', 3),
    'jaw_worm': ('worm', 4),
    'louse': ('louse', 2),
    'louse_normal': ('louse', 2),
    'louse_defensive': ('louse', 2),
    'louse_red': ('louse', 6),
    'spike_slime_s': ('slime', 1),
    'spike_slime_m': ('slime', 1),
    'spike_slime_l': ('slime', 1),
    'acid_slime_s': ('slime', 2),
    'acid_slime_m': ('slime', 2),
    'acid_slime_l': ('slime', 2),
    'slime': ('slime', 2),
    'slime_boss': ('boss_blob', 2),
    'the_guardian': ('boss_machine', 5),
    'hexaghost': ('floating_orb', 3),
    'fat_gremlin': ('gremlin', 4),
    'mad_gremlin': ('gremlin', 0),
    'sneaky_gremlin': ('gremlin', 3),
    'shield_gremlin': ('gremlin', 1),
    'gremlin_wizard': ('gremlin', 7),
    'gremlin_nob': ('boss_machine', 0),
    'blue_slaver': ('slaver', 1),
    'red_slaver': ('slaver', 6),
    'taskmaster': ('slaver', 4),
    'fungi_beast': ('plant', 3),
    'looter': ('humanoid', 5),
    'sentry': ('sentinel', 5),
    'spheric_guardian': ('floating_orb', 4),
    'centurion': ('sentinel', 4),
    'mystic': ('humanoid', 3),
    'chosen': ('humanoid', 3),
    'byrd': ('ghost', 2),
    'shelled_parasite': ('beast', 2),
    'spire_growth': ('plant', 7),
    'transient': ('ghost', 5),
    'snake_plant': ('plant', 7),
    'the_champ': ('boss_machine', 6),
    'bronze_automaton': ('boss_machine', 4),
    'bronze_orb': ('floating_orb', 4),
    'torch_head': ('crystal', 0),
    'darkling': ('ghost', 3),
    'orb_walker': ('construct', 7),
    'spiker': ('crystal', 5),
    'repulsor': ('construct', 3),
    'exploder': ('crystal', 0),
    'awakened_one': ('boss_blob', 7),
    'time_eater': ('boss_machine', 3),
    'donu': ('construct', 0),
    'deca': ('construct', 1),
    'shapes': ('crystal', 5),
    'the_snecko': ('beast', 2),
    'dagger': ('crystal', 5),
    'louse_boss': ('boss_blob', 2),
}

# 二维元素的手写覆盖（卡/遗物/药水/状态）：只影响颜色，字母仍由规则给。
BADGE_OVERRIDES = {
    'cards': {'strike': 0, 'defend': 1, 'bash': 6, 'neutralize': 2, 'ascenders_bane': 3},
    'relics': {'burning_blood': 0, 'anchor': 1, 'bag_of_prep': 2},
    'potions': {'fire_potion': 0, 'block_potion': 1, 'energy_potion': 4},
    'statuses': {'standard.vulnerable': 6, 'standard.weak': 4, 'standard.strength': 0,
                 'standard.dexterity': 1, 'standard.frail': 3},
}


def stable_hash(text):
    """FNV-1a 32 位：**稳定**（不依赖 Python 的 `hash()`，它带随机种子）。"""
    value = 0x811C9DC5
    for byte in text.encode('utf-8'):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


#: §398：闸门 45 用 Node 重算这个文件的 sha256 并与清单里的 `GENERATOR_SHA` 比对。
def generator_sha():
    """这个 .py 文件自己的 sha256（"生成器变了却没重跑"的直接判据）。"""
    with open(os.path.abspath(__file__), 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


#: §398：哈希对拍表 —— 覆盖 ASCII / 多字节 / 空串 / 下划线。
#: 闸门 45 拿它逐条验证 `registry.ts` 的 JS 实现（`Math.imul` + UTF-8）与这里逐字节一致。
HASH_FIXTURES = [
    {'text': '', 'hash': 2166136261},
    {'text': 'strike', 'hash': 632598351},
    {'text': 'not_a_real_enemy', 'hash': 2453344752},
    {'text': 'new_monster_id', 'hash': 2615040844},
    {'text': '中文', 'hash': 3297308741},
    {'text': 'standard.vulnerable|p', 'hash': stable_hash('standard.vulnerable|p')},
]


def letters_for(asset_id):
    """内容 id → **两位大写字母**。

    规则（确定性，可单测）：
    1. 去掉升级后缀 `+`（`strike+` 与 `strike` 同一组字母 —— 升级不改变"这是哪张牌"）；
    2. 按 `_` / `.` / `-` 切词；取**前两个词的首字母**（`twin_strike` → `TS`）；
    3. 只有一个词时取**前两个字符**（`strike` → `ST`、`bash` → `BA`）；
    4. 不足两位就用 `X` 补齐（`hex` → `HE`；`a` → `AX`）。
    """
    base = asset_id.rstrip('+')
    words = [word for word in base.replace('.', '_').replace('-', '_').split('_') if word]
    if len(words) >= 2:
        letters = words[0][:1] + words[1][:1]
    elif words:
        letters = words[0][:2]
    else:
        letters = ''
    letters = letters.upper()
    while len(letters) < 2:
        letters += 'X'
    return letters[:2]


def enemy_asset(monster_id, tier):
    """敌人 id → { archetype, palette, scale, boss }。覆盖优先，否则确定性规则。"""
    override = ENEMY_OVERRIDES.get(monster_id)
    if override:
        archetype, palette = override
    else:
        # 没有覆盖：按稳定哈希挑原型/调色板。**没有洞** —— 新怪物自动有素材。
        archetype = ARCHETYPES[stable_hash(monster_id) % len(ARCHETYPES)]
        palette = stable_hash(monster_id + '|p') % len(PALETTES)
    # §398：**玩法身份**（boss/elite/normal）与**视觉体型**（scale）分开。
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
    }


def badge_asset(kind, asset_id):
    palette = BADGE_OVERRIDES.get(kind, {}).get(asset_id)
    if palette is None:
        palette = stable_hash(kind + '|' + asset_id) % len(PALETTES)
    return {'letters': letters_for(asset_id), 'palette': palette}


def build():
    content = json.load(io.open(CONTENT, encoding='utf-8'))
    enemies = {}
    for monster in content.get('Monsters') or []:
        monster_id = monster.get('Id')
        if monster_id:
            enemies[monster_id] = enemy_asset(monster_id, monster.get('Tier'))
    badges = {}
    for kind, key in (('cards', 'Cards'), ('relics', 'Relics'), ('potions', 'Potions'), ('statuses', 'Statuses')):
        table = {}
        for row in content.get(key) or []:
            asset_id = row.get('Id')
            if asset_id:
                table[asset_id] = badge_asset(kind, asset_id)
        badges[kind] = table
    return enemies, badges


def render(enemies, badges):
    counts = {'enemies': len(enemies)}
    for kind, table in badges.items():
        counts[kind] = len(table)
    lines = [
        '// 生成物：`python native/build_assets.py` 重建，**不要手改**。',
        '//',
        '// 素材清单：内容 id → 素材描述。**穷尽**（每个内容 id 都有一条），所以"内容加了东西',
        '// 而美术没跟上"在结构上不会静默 —— 清单是生成的，注册表对缺失 id 还会计数（见 registry.ts）。',
        '//',
        '// 三维敌人：16 种「立体几何排列组合」原型（原型本体是 `geometry.ts` 里的纯数据）。',
        '// 二维元素：两位大写字母 + 调色板（`letters_for` 的规则见生成器文件头）。',
        '',
        '// §398：生成器**自己的** sha256（这个 .py 文件的）—— 闸门 45 用 Node 重算并与它比对。',
        '// 改了生成器（palette/scale/boss 规则…）却没重跑 ⇒ 指纹对不上 ⇒ 闸门红。',
        '// 这条是审阅 §4 指出的盲点：验收链的 PATH 是剥空的，跑不了 python，但**能**算 sha256。',
        'export const GENERATOR_SHA = ' + json.dumps(generator_sha(), ensure_ascii=False) + ';',
        '',
        '// §398：哈希对拍表（Python 侧算好的真值）。闸门 45 用它逐条验证 `registry.ts` 的 JS 实现',
        '// 与生成器**逐字节**一致 —— 否则"清单里有的 id"与"降级时的 id"会落到不同原型/调色板。',
        'export const HASH_FIXTURES: readonly { text: string; hash: number }[] = '
        + json.dumps(HASH_FIXTURES, ensure_ascii=False, indent=1) + ';',
        '',
        'export interface EnemyAsset {',
        '  readonly archetype: string;',
        '  readonly palette: number;',
        '  readonly scale: number;',
        '  readonly boss: boolean;',
        '  /** §398：玩法身份（`boss` / `elite` / `normal`）。`boss` 只留给真 Boss，精英不再冒充。 */',
        '  readonly tier: "boss" | "elite" | "normal";',
        '}',
        '',
        'export interface BadgeAsset {',
        '  readonly letters: string;',
        '  readonly palette: number;',
        '}',
        '',
        'export const ASSET_COUNTS = ' + json.dumps(counts, ensure_ascii=False, sort_keys=True) + ';',
        '',
        'export const PALETTES = ' + json.dumps(PALETTES, ensure_ascii=False, indent=1) + ' as const;',
        '',
        'export const ARCHETYPES = ' + json.dumps(ARCHETYPES, ensure_ascii=False) + ' as const;',
        '',
        'export const ENEMY_ASSETS: Record<string, EnemyAsset> = ' + json.dumps(enemies, ensure_ascii=False, indent=1) + ';',
        '',
        'export const BADGE_ASSETS: Record<"cards" | "relics" | "potions" | "statuses", Record<string, BadgeAsset>> = '
        + json.dumps(badges, ensure_ascii=False, indent=1) + ';',
        '',
    ]
    return NL.join(lines)


def main():
    enemies, badges = build()
    text = render(enemies, badges)
    if '--check' in sys.argv:
        try:
            current = io.open(OUT, encoding='utf-8').read()
        except FileNotFoundError:
            print('ASSETS_CHECK FAIL: 清单不存在，先跑 `python native/build_assets.py`')
            return 1
        if current != text:
            print('ASSETS_CHECK FAIL: 清单与内容不一致（内容变了？重跑生成器）')
            return 1
        print('ASSETS_CHECK PASS enemies=%d cards=%d relics=%d potions=%d statuses=%d' % (
            len(enemies), len(badges['cards']), len(badges['relics']), len(badges['potions']), len(badges['statuses'])))
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8', newline=NL).write(text)
    print('写出 %s' % os.path.relpath(OUT, ROOT))
    print('  敌人 %d / 卡牌 %d / 遗物 %d / 药水 %d / 状态 %d' % (
        len(enemies), len(badges['cards']), len(badges['relics']), len(badges['potions']), len(badges['statuses'])))
    used = {}
    for asset in enemies.values():
        used[asset['archetype']] = used.get(asset['archetype'], 0) + 1
    print('  原型使用：%s' % ', '.join('%s=%d' % (k, v) for k, v in sorted(used.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
