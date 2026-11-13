"""幕布（`#actCurtain`）：`act` 变大 ⇒ 一屏 1.6 秒的幕间演出。

## 规格（`ui-state-model.md` §2.3）

> 纯演出，1.6 秒自动淡出。触发条件是"`act` 变大"（T1），**不需要**任何新导出。

所以它**不持有任何游戏事实**：只是把"幕号变了"这件事画出来。这与 §368 的冻结、§365 的 Beat
同一条纪律 —— 演出层不写状态，所以"关掉演出"不可能改变玩法。

## 三条实现约束

1. **一个写者**：`RunStore.curtain` 是唯一来源，组件只读它 + 调 `dismissCurtain()`；
2. **不挡操作**：`pointer-events: none`，只有"点一下继续"那一层在需要时可点（`pointer-events: auto`），
   而且它**不 gate** 任何动作 —— 点不点都能继续玩（1.6 秒后自己走）；
3. **关动画就不播**：`?motion=off`（或系统 `prefers-reduced-motion`）时 `RunStore` 直接不置位。
"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── RunStore：检测 act 变大 ────────────────────────────────────────────────
patch('web-next/src/run/RunStore.ts', [
    (
        'state curtain',
        '''  /** 幕间待选的 Boss 遗物（空 = 没有待选）。 */
  readonly bossRelics: readonly string[];''',
        '''  /** 幕间待选的 Boss 遗物（空 = 没有待选）。 */
  readonly bossRelics: readonly string[];
  /**
   * 幕间幕布（`ui-state-model.md` §2.3）：`null` = 没有幕布。
   *
   * **纯演出**：只记"第几幕"，不参与任何判断。`seq` 让组件知道"又换了一次幕"
   * （同一幕连开两局时也要能重播）。
   */
  readonly curtain: { readonly act: number; readonly seq: number } | null;''',
    ),
    (
        'state init curtain',
        '''      act: 1,
      bossRelics: [],''',
        '''      act: 1,
      bossRelics: [],
      curtain: null,''',
    ),
    (
        'fields',
        '''  /** 测试钩子注入的违约（`?debug` 下用，见 `injectViolation`）。 */
  private injectedViolation: string | null = null;''',
        '''  /** 测试钩子注入的违约（`?debug` 下用，见 `injectViolation`）。 */
  private injectedViolation: string | null = null;
  /** 上一次见到的幕号（幕布靠它判"变大了"）。 */
  private lastAct = 0;
  private curtainSeq = 0;
  /** 关动画（`?motion=off` / 系统偏好）：幕布直接不播。 */
  private readonly motionOff: boolean;''',
    ),
    (
        'ctor motion',
        '''  constructor(host: WasmHost) {
    this.host = host;''',
        '''  constructor(host: WasmHost) {
    this.host = host;
    // 与 `CombatScreen` 同一个优先级：URL > localStorage > 系统。演出层读的是同一份偏好。
    const param = new URLSearchParams(window.location.search).get("motion");
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem("rd.motion");
    } catch {
      stored = null;
    }
    const prefersReduced =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
        : false;
    this.motionOff =
      param === "off" ? true : param === "on" ? false : stored === "off" ? true : stored === "on" ? false : prefersReduced;''',
    ),
    (
        'detect act change',
        '''      act: raw.exists ? raw.act : 0,''',
        '''      act: raw.exists ? raw.act : 0,
      // §2.3：**触发条件是"act 变大"**（不需要新导出）。换幕时内核已经把 floor 归 0、地图换新，
      // 玩家需要注意到这件事 —— 否则"回到第 0 层"看起来像 bug。
      curtain: this.nextCurtain(raw.exists ? raw.act : 0),''',
    ),
    (
        'curtain helper',
        '''  /** 现在能不能改状态：`null` = 能；否则是"为什么不能"。 */''',
        '''  /**
   * 幕布判定：`act` **变大** ⇒ 置一次幕布。纯演出，不改任何游戏事实。
   *
   * `act` 变小（重开一局）不算换幕 —— 那是"新的一局"，标题屏已经说清了。
   */
  private nextCurtain(act: number): RunState["curtain"] {
    const previous = this.lastAct;
    this.lastAct = act;
    if (!(act > previous) || previous === 0) return this.state.curtain;
    if (this.motionOff) return null;
    this.curtainSeq += 1;
    return { act, seq: this.curtainSeq };
  }

  /** 关掉幕布（点一下 / 1.6 秒到）。 */
  dismissCurtain(): void {
    if (this.state.curtain === null) return;
    this.state = { ...this.state, curtain: null };
    this.emit();
  }

  /** 现在能不能改状态：`null` = 能；否则是"为什么不能"。 */''',
    ),
    (
        'clear on startRun',
        '''    this.frozenReason = null;
    this.injectedViolation = null;''',
        '''    this.frozenReason = null;
    this.injectedViolation = null;
    // 新开一局：幕号回到 1，幕布不该因为"上次是 3"而重播。
    this.lastAct = 0;
    this.state = { ...this.state, curtain: null };''',
    ),
])
print('done')
