"""§399 R1：把 `Beat` 的因果信息接进演出（审阅 §6 的垂直切片）。

## 改动

1. `beats.ts::BeatEffect` 增加 `def` / `origin` / `effectKey` / `anchorSlot` / `appearanceId` /
   `phase` —— 以前 `planBeats` 把 `def`（卡/状态定义）与 `actor` 全丢了，于是"Strike 的斩击"与
   "Bash 的重击"在数据上一模一样。
2. `planBeats` 用 `presentation/cues.ts::translateAll` 生成 Cue，再从
   `presentation/registry.ts::recipeFor(effectKey)` 取配方（颜色/形状/时长/震屏）。
   **文案仍由 `describe()` 给**（中文文案是显示层的事，Cue 只带语义）。
3. `BeatLayer` 用配方画（`data-cue-shape` / `data-cue-key` / 震屏 class），并把**冻结锚点**
   用起来：播放时若该槽位的外观 id 已经变了（Boss 分裂/召唤/死亡后槽位重用），
   退回 Cue 冻结的槽位，而不是画在新对象头上。

⚠️ 纪律不变：这一层仍然**只读** beat，纯函数，不碰局面。
"""

import io


def patch(path, pairs, label):
    t = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert t.count(old) == 1, '%s: %r (%d)' % (label, old[:60], t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', label)


# ── 1. BeatEffect 带上因果信息 ─────────────────────────────────────────────
patch(
    'web-next/src/combat/beats.ts',
    [
        (
            '''// 动画最容易写成一团 `setTimeout` + 全局状态，然后"关掉动画"就变成另一条代码路径。
// 这里把"什么时候播到第几条"做成 `(state, dtMs) -> state` 的纯函数：闸门 37 不需要浏览器
// 就能把 skip / 快进 / 降级 / 上限全部测掉。''',
            '''// 动画最容易写成一团 `setTimeout` + 全局状态，然后"关掉动画"就变成另一条代码路径。
// 这里把"什么时候播到第几条"做成 `(state, dtMs) -> state` 的纯函数：闸门 37 不需要浏览器
// 就能把 skip / 快进 / 降级 / 上限全部测掉。
//
// ## §399：因果信息不再丢
//
// 内核的 Beat 带 `def`（卡/状态**定义 id**）、`actor`、`target`、`flags`、`a/b/c`。
// 第一版只留下了 `{kind, at, text, tone, duration}`，于是"Strike 的斩击"与"Bash 的重击"
// 在数据上一模一样（审阅 §6）。现在 `BeatEffect` 原样带 `def` / `actor` / `target` / `flags`，
// 外加 `presentation/cues.ts` 翻出来的 `origin` / `effectKey` / `phase` / 冻结锚点。
//
// 文案仍是 `describe()` 的中文；`effectKey` 只决定**视觉配方**（颜色/形状/时长/震屏）。''',
        ),
        (
            '''/** 演出基调（决定颜色与动画方向）。 */''',
            '''import { translateAll, type PresentationCue } from "../presentation/cues.js";
import { recipeFor } from "../presentation/registry.js";

/** 演出基调（决定颜色与动画方向）。 */''',
        ),
        (
            '''export interface BeatEffect {
  readonly id: number;
  readonly kind: number;
  readonly at: number;
  readonly text: string;
  readonly tone: BeatTone;
  /** 播多久（毫秒）。`0` = 立即结束（只留一行日志式提示）。 */
  readonly duration: number;
}''',
            '''export interface BeatEffect {
  readonly id: number;
  readonly kind: number;
  readonly at: number;
  readonly text: string;
  readonly tone: BeatTone;
  /** 播多久（毫秒）。`0` = 立即结束（只留一行日志式提示）。 */
  readonly duration: number;
  /**
   * §399：内核给的**定义 id**（`strike` / `standard.poison` / 空串）。
   *
   * ⚠️ 以前这里没有它 —— 于是"哪张卡打的""哪个状态变的"在演出层不可知。
   */
  readonly def: string;
  /** §399：来源（卡 / 状态 / 敌人招式 / 系统）。无法证明时是 `system`，**不猜**。 */
  readonly origin: PresentationCue["origin"];
  /** §399：稳定 key（`damage.dot` / `card.strike`），`presentation/registry.ts` 用它查配方。 */
  readonly effectKey: string;
  /** §399：演出阶段（`cast` / `hit` / `resolve`）。将来给 3D 分轨用。 */
  readonly phase: PresentationCue["phase"];
  /**
   * §399：**冻结的锚点**（Cue 创建那一刻的槽位与外观 id）。
   *
   * 播放时若该槽位的外观已经变了（Boss 分裂 / 召唤 / 死亡后槽位重用），就退回这里，
   * 而不是把旧事件的飘字画在**新**对象头顶（审阅 §6 的陷阱 1）。
   */
  readonly anchorSlot: number;
  readonly appearanceId: string;
}''',
        ),
    ],
    'beats.ts types',
)
