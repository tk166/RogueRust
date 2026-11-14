"""§388：状态的中文名 —— 三条来源，按顺序，全部**内容驱动**。

## 玩家报的

"一些状态依旧显示英文例如 orichalcum 和 incense_burner"。

## 根因

`zh.ts` 的 `statuses` 表只有 **13** 条（来自仓库里的 `legacy/statuses.json`），而内容包有
**150** 条。`orichalcum` / `incense_burner` 这两条是**遗物挂的状态**（`StartCombatStatus`），
它们根本不在那张小表里 ⇒ 界面上是英文 id（美化后 `orichalcum`）。

## 三条来源（按顺序，命中就停）

1. **legacy 表**（原来的 13 条 + 五条轴）；
2. **跨表复用**：`standard.X` 里的 `X` 在 `relics` / `cards` / `potions` / `monsters` 里
   已经翻译过 ⇒ 直接用那个中文名。这条覆盖了 `orichalcum`（遗物）、`corruption`（卡）、
   `metallicize`（卡）… 一共 24 条。理由：状态名与它来源的名字**本来就是一回事**，
   两份翻译只会漂（§382 的老病）。
3. **人工译名表**（`STATUS_ZH`）：剩下的是"只在状态里出现"的词（`curl_up` / `artifact` /
   `intangible` …）。来源是官方中文本地化；没有两源核对，**只用作显示名**，不进任何规则。

查不到的仍然走运行时的"美化 id"（`spike slime l`），并且闸门 56 的显式白名单会盯着它。
"""

import io

PATH = 'native/build_zh_i18n.py'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''    # ── 状态：spire-archive 的 powers 只有英文 ⇒ 用仓库自己的中文 ────────────────
    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = {'name': legacy[axis]}
    for status_id, name in legacy.items():
        out['statuses'].setdefault(status_id, {'name': name})'''

NEW = '''    # ── 状态：三条来源，按顺序（§388）────────────────────────────────────────
    statuses = json.load(io.open(os.path.join(LEGACY, 'statuses.json'), encoding='utf-8'))
    legacy = {item['id']: item['name'] for item in statuses}
    for axis in ('strength', 'vulnerable', 'weak', 'dexterity', 'frail'):
        if axis in legacy:
            out['statuses']['standard.' + axis] = {'name': legacy[axis]}
    for status_id, name in legacy.items():
        out['statuses'].setdefault(status_id, {'name': name})

    # ② 跨表复用：`standard.X` 的 `X` 在别的表里已经翻译过 ⇒ 用那个名字。
    # 状态与它来源（遗物/卡/药水）本来就是同一个词，两份翻译只会漂。
    reused = 0
    for status in content['Statuses']:
        status_id = status['Id']
        if status_id in out['statuses']:
            continue
        short = status_id.split('.', 1)[1] if '.' in status_id else status_id
        for table in ('relics', 'cards', 'potions', 'monsters'):
            entry = out[table].get(short)
            if entry and entry.get('name'):
                out['statuses'][status_id] = {'name': entry['name']}
                reused += 1
                break
    # ③ 人工译名（只在状态里出现的词）。来源：官方中文本地化。
    # ⚠️ 这些**只做显示名**，不进任何规则判定（规则一律走 id）。
    for status_id, name in STATUS_ZH.items():
        out['statuses'].setdefault(status_id, {'name': name})
    print('  状态复用   %3d 条（跨表）+ %d 条（人工译名表）' % (reused, len(STATUS_ZH)))'''

assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# 译名表放在文件顶部常量区（`META_OUT` 之后）
ANCHOR = '''META_OUT = os.path.join(ROOT, 'web-next', 'src', 'view', 'cardMeta.ts')'''
assert t.count(ANCHOR) == 1
TABLE = '''META_OUT = os.path.join(ROOT, 'web-next', 'src', 'view', 'cardMeta.ts')

#: 只在状态里出现的词 → 中文（§388 第 ③ 层）。
#:
#: ⚠️ **只作显示名**：任何规则判定都走 id，不走这里。来源是官方中文本地化；
#: 这些条目没有第二来源核对（不像 wiki 数值那样），所以不写进 `sts-wiki-gap.md` 的账。
STATUS_ZH = {
    'standard.artifact': '神器',
    'standard.cap_cost_at': '费用上限',
    'standard.confusion': '混乱',
    'standard.constricted': '紧束',
    'standard.curiosity': '好奇',
    'standard.curl_up': '蜷缩',
    'standard.double_damage': '双倍伤害',
    'standard.draw_reduction': '抽牌减少',
    'standard.enrage': '激怒',
    'standard.entangle_ready': '缠绕就绪',
    'standard.entangled': '缠绕',
    'standard.fading': '消逝',
    'standard.flying': '飞行',
    'standard.hex': '诅咒',
    'standard.intangible': '无形',
    'standard.lagavulin_asleep': '沉睡',
    'standard.lose_dexterity': '失去敏捷',
    'standard.lose_strength': '失去力量',
    'standard.malleable': '可塑',
    'standard.mode_shift': '模式转换',
    'standard.nightmare_pending': '噩梦待发',
    'standard.no_block_from_cards': '卡牌不提供格挡',
    'standard.no_draw': '无法抽牌',
    'standard.omega': '欧米伽',
    'standard.painful_stabs': '痛苦刺击',
    'standard.phantom_veil': '幻影面纱',
    'standard.phase_split': '分裂（相位）',
    'standard.plated_armor': '镀甲',
    'standard.poison': '中毒',
    'standard.regain_strength': '恢复力量',
    'standard.regen': '再生',
    'standard.sharp_hide': '尖刺外壳',
    'standard.slow': '迟缓',
    'standard.split': '分裂',
    'standard.split_acid_l': '分裂：大型酸液',
    'standard.split_spike_l': '分裂：大型尖刺',
    'standard.spore_cloud': '孢子云',
    'standard.stasis': '停滞',
    'standard.stasis_ready': '停滞就绪',
    'standard.the_bomb_damage': '炸弹伤害',
    'standard.time_warp': '时间扭曲',
    'standard.unawakened': '未觉醒',
}'''
t = t.replace(ANCHOR, TABLE)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('generator: 三条来源')
