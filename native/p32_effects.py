"""§382：事件/祝福的效果标签必须覆盖内核**全部**的效果码，`-1` 不许写成"未知效果"。

## 玩家报的

"事件里面的祈祷遇到了不明所以的'未知效果'"。

祈祷 = `wing_statue`（翅膀雕像）的第一个选项：`[祈祷] 从你的牌组中移除一张牌。失去 生命。`
它的原子是 `remove_card` + `damage`。`remove_card` 在内核里是码 **6**，而界面的
`effectLabel` 只认识 **1..5** ⇒ 屏幕上打出 `未知效果 6（0）`。

## 两个独立的错

1. **词表漂了**：内核的效果码到 16（§143/§278/§280/§285 陆续加的），界面停在 §9 的 5 个。
   "同一个词表被两处认识就一定漂"（FACT §4.20）。
2. **`-1` 被当成"未知"**：`-1` 在内核里的意思是**"这一条没有效果码"**（§279–§324 的一贯做法：
   真正的信息在内容字符串里，比如 `card:<id>` / `relic_lose:<id>` / `transform_choose:<n>`，
   而选项自己的文字已经把话说清楚了）。把它画成"未知效果 -1（0）"是在**报告一个不存在的错误**。

## 修法

* `effectLabel` 覆盖 1..16，未知码仍然响亮（`未知效果 N`）—— 那是真的坏了；
* `-1` 返回**空串**，`effectSummary` 跳过空串；全空 ⇒ 返回空串（调用方不画那一行）。
"""

import io

PATH = 'web-next/src/run/models.ts'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''// ── 事件效果（与祝福同一套判别值）──────────────────────────────────────────
export const EFFECT = {
  heal: 1,
  gold: 2,
  loseHealth: 3,
  maxHealth: 4,
  nothing: 5,
} as const;

/**
 * 效果判别值 → 人话。
 *
 * ⚠️ `nothing` 是 **5**，不是 0：0 在别处是"没有"，这里"没有效果"有专门的取值，
 * 所以不能拿 `kind === 0` 判"无"（那会把**所有**未知效果都显示成"无"）。
 */
export function effectLabel(kind: number, amount: number): string {
  switch (kind) {
    case EFFECT.heal:
      return `回复 ${amount} 点生命`;
    case EFFECT.gold:
      return `获得 ${amount} 金币`;
    case EFFECT.loseHealth:
      return `失去 ${amount} 点生命`;
    case EFFECT.maxHealth:
      return `生命上限 +${amount}`;
    case EFFECT.nothing:
      return "无";
    default:
      return `未知效果 ${kind}（${amount}）`;
  }
}

/** 一条选项的效果列表 → 一句话（多条用 ` · ` 连）。 */
export function effectSummary(effects: readonly { kind: number; amount: number }[]): string {
  if (effects.length === 0) return "无";
  return effects.map((effect) => effectLabel(effect.kind, effect.amount)).join(" · ");
}'''

NEW = '''// ── 事件效果（与祝福同一套判别值）──────────────────────────────────────────
/**
 * 效果码 —— **内核的闭集**（`kernel/rd-wasm/src/run.rs::effect_code` / `effect_code_of`）。
 *
 * ⚠️ 这张表必须与内核**逐条对齐**：§9 只有 1..5，之后 §143（6..8）、§278（11/12）、
 * §280（13/14/15）、§285（16）陆续加码，界面停在 1..5 就把 `remove_card`（6）显示成
 * "未知效果 6（0）"（玩家实测：事件「翅膀雕像」的 [祈祷] 选项）。
 *
 * `none = -1` 不是"未知"：内核用它表示**"这一条没有效果码"** —— 真正的作用在内容字符串里
 * （`card:<id>` / `relic_lose:<id>` / `transform_choose:<n>` …），而选项自己的文字已经说清了。
 */
export const EFFECT = {
  none: -1,
  heal: 1,
  gold: 2,
  loseHealth: 3,
  maxHealth: 4,
  nothing: 5,
  removeCard: 6,
  upgradeCard: 7,
  transformCard: 8,
  gainCurse: 9,
  gainRelic: 10,
  loseHealthPercent: 11,
  loseMaxHealthPercent: 12,
  goldCost: 13,
  healPercent: 14,
  healFull: 15,
  goldRandom: 16,
} as const;

/**
 * 效果判别值 → 人话。
 *
 * ⚠️ `nothing` 是 **5**，不是 0：0 在别处是"没有"，这里"没有效果"有专门的取值，
 * 所以不能拿 `kind === 0` 判"无"（那会把**所有**未知效果都显示成"无"）。
 *
 * ⚠️ `-1` 返回**空串**（"没有效果码"≠"未知"）：调用方不画那一行。把它写成"未知效果 -1"
 * 是在报告一个不存在的错误 —— 玩家会以为事件坏了。
 */
export function effectLabel(kind: number, amount: number): string {
  switch (kind) {
    case EFFECT.none:
      return "";
    case EFFECT.heal:
      return `回复 ${amount} 点生命`;
    case EFFECT.gold:
      return `获得 ${amount} 金币`;
    case EFFECT.loseHealth:
      return `失去 ${amount} 点生命`;
    case EFFECT.maxHealth:
      return `生命上限 +${amount}`;
    case EFFECT.nothing:
      return "无";
    case EFFECT.removeCard:
      return "从牌组移除一张牌";
    case EFFECT.upgradeCard:
      return "升级一张牌";
    case EFFECT.transformCard:
      return "变化一张牌";
    case EFFECT.gainCurse:
      return "获得一张诅咒牌";
    case EFFECT.gainRelic:
      return "获得一件遗物";
    // §278：`amount` 是**千分比**（`250` = 25%）—— 内核已经把它换算成同一个单位。
    case EFFECT.loseHealthPercent:
      return `失去 ${Math.round(amount / 10)}% 最大生命`;
    case EFFECT.loseMaxHealthPercent:
      return `生命上限 −${Math.round(amount / 10)}%`;
    case EFFECT.goldCost:
      return `支付 ${amount} 金币`;
    case EFFECT.healPercent:
      return `回复 ${Math.round(amount / 10)}% 最大生命`;
    case EFFECT.healFull:
      return "回复全部生命";
    case EFFECT.goldRandom:
      return "获得随机数量的金币";
    default:
      // 真正的"未知"：内核加了一个码而界面没跟上。响亮，但只有这一条路。
      return `未知效果 ${kind}（${amount}）`;
  }
}

/**
 * 一条选项的效果列表 → 一句话（多条用 ` · ` 连）。
 *
 * 全空（每条都是 `-1`，或列表本身为空）⇒ 返回**空串**：调用方据此**不画**这一行，
 * 而不是画一个"无"。空列表仍然返回"无"（那确实是"没有效果"）。
 */
export function effectSummary(effects: readonly { kind: number; amount: number }[]): string {
  if (effects.length === 0) return "无";
  return effects
    .map((effect) => effectLabel(effect.kind, effect.amount))
    .filter((line) => line.length > 0)
    .join(" · ");
}'''

assert t.count(OLD) == 1
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('models: effectLabel 覆盖 1..16，-1 为空串')

# 调用方：空串就不画那一行（否则留一条空 span 占位）。
PATH2 = 'web-next/src/run/scenes/EventScene.tsx'
t2 = io.open(PATH2, encoding='utf-8').read()
OLD2 = '''            <span className="event-option-effect muted">{effectSummary(option.effects)}</span>'''
NEW2 = '''            {/* §382：`-1`（没有效果码）时 `effectSummary` 给空串 ⇒ **不画**这一行，
                而不是画"未知效果 -1"。选项自己的文字已经把话说清楚了。 */}
            {effectSummary(option.effects) !== "" && (
              <span className="event-option-effect muted">{effectSummary(option.effects)}</span>
            )}'''
assert t2.count(OLD2) == 1
t2 = t2.replace(OLD2, NEW2)
io.open(PATH2, 'w', encoding='utf-8', newline='\n').write(t2)
print('EventScene: 空串不画')

# 祝福屏那份**复制品**也要改（同一个词表两处认识 —— 正是这次的病根）。
PATH3 = 'web-next/src/run/scenes/BlessingScene.tsx'
t3 = io.open(PATH3, encoding='utf-8').read()
OLD3 = '''    default:
      return `未知效果 ${kind}（${amount}）`;
  }
}'''
NEW3 = '''    // §382：祝福这一侧**复用**事件那一份词表（同一个闭集）。原来这里是**另一份**
    // `switch`，于是"内核加了码、两处各漂一次"——这次就是它把 `remove_card`(6) 画成了
    // "未知效果 6（0）"。
    default:
      return effectLabel(kind, amount);
  }
}'''
assert t3.count(OLD3) == 1
t3 = t3.replace(OLD3, NEW3)
io.open(PATH3, 'w', encoding='utf-8', newline='\n').write(t3)
print('BlessingScene: 复用 effectLabel')
