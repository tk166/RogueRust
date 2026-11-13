"""修 #1：把"冻结"变成**操作层**的唯一边界（粘性），而不是按钮层的装饰。

三处：
1. `RunStore`：粘性 `frozen` + 所有动作入口统一 `canMutate()`；
2. `GameStore`：注入 `dispatchGuard`（`CombatScreen` 直接调 `dispatch`，只守 RunStore 无效）；
3. `RunApp`：`blocked` 传给**所有**场景与覆盖层（祝福/奖励/终局以前都没有）。
"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. GameStore：dispatchGuard ───────────────────────────────────────────────
patch(
    'web-next/src/wasm/store.ts',
    [
        (
            'reason union',
            '''  readonly reason: "accepted" | "rejected" | "finished" | "broken";''',
            '''  /**
   * `"frozen"`：**契约违约后界面被冻结**，这一步根本没有发给内核（第十五轮 Review §2）。
   *
   * 与 `"rejected"` 的区别很重要：`rejected` 是"内核拒绝了玩家这一手"，
   * `frozen` 是"我们不敢再问内核了" —— 前者可以继续玩，后者必须停下来看诊断。
   */
  readonly reason: "accepted" | "rejected" | "finished" | "broken" | "frozen";''',
        ),
        (
            'guard field',
            '''  private lastBeats: { beats: readonly Beat[]; dropped: number; seq: number } = {
    beats: [],
    dropped: 0,
    seq: 0,
  };''',
            '''  private lastBeats: { beats: readonly Beat[]; dropped: number; seq: number } = {
    beats: [],
    dropped: 0,
    seq: 0,
  };
  /**
   * 冻结判据（由 `RunStore` 注入）。
   *
   * ⚠️ 为什么必须在这里：`CombatScreen` 是**直接**调 `GameStore.dispatch` 的（P2 的设计），
   * 只在 `RunStore` 的动作方法上把门，战斗动作就完全绕过冻结 —— 第十五轮 Review §2 指出的
   * 正是这件事。返回非 `null` 表示"现在不许动"，字符串是给玩家看的原因。
   */
  private dispatchGuard: (() => string | null) | null = null;

  /** 注入冻结判据（`RunStore` 在构造战斗 store 时调用）。 */
  setDispatchGuard(guard: (() => string | null) | null): void {
    this.dispatchGuard = guard;
  }''',
        ),
        (
            'guard check in dispatch',
            '''  dispatch(action: CombatAction): DispatchResult {
    const before = this.current;
    if (!before) throw new Error("没有战斗会话：先 fight_begin");''',
            '''  dispatch(action: CombatAction): DispatchResult {
    const before = this.current;
    if (!before) throw new Error("没有战斗会话：先 fight_begin");
    // **冻结时一步都不发给内核**（连 `rd_env_step` 都不调）：这样"冻结"是可证的
    // （观察向量不变），而不是"发了但内核没理"。
    const blocked = this.dispatchGuard?.() ?? null;
    if (blocked !== null) {
      return {
        accepted: false,
        code: STEP_REJECTED,
        unchanged: true,
        reason: "frozen",
        action,
        before,
        after: before,
        beats: [],
        beatsDropped: 0,
      };
    }''',
        ),
        (
            'contract helper',
            '''  static isContractViolation(result: DispatchResult): boolean {
    return !result.accepted && !result.unchanged;
  }''',
            '''  static isContractViolation(result: DispatchResult): boolean {
    return !result.accepted && !result.unchanged;
  }

  /** 界面被冻结（契约违约之后）—— 不是"玩家操作非法"。 */
  static isFrozen(result: DispatchResult): boolean {
    return result.reason === "frozen";
  }''',
        ),
    ],
)

# ── 2. RunStore：粘性 frozen + 统一 canMutate ────────────────────────────────
patch(
    'web-next/src/run/RunStore.ts',
    [
        (
            'frozen fields',
            '''  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;''',
            '''  /**
   * **粘性冻结**（第十五轮 Review §2）。
   *
   * 一旦对账失败就置位，只有"重开一局"能解除 —— **不**随 `violations` 变空而自动解冻。
   * 理由：违约说明 ABI 已经不可信，而"下一帧看起来正常了"不构成恢复的证据；自动解冻会让
   * 玩家在**半可信**状态里继续操作（这比直接停下来更坏）。
   */
  private frozenReason: string | null = null;
  /** 测试钩子注入的违约（`?debug` 下用，见 `injectViolation`）。 */
  private injectedViolation: string | null = null;
  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;''',
        ),
        (
            'reconcile includes injected',
            '''    if (scene.unknownPending !== null) {
      bad.push(`内核给了未知相位 ${scene.unknownPending}（UI 的 PENDING_SCENE 表没跟上）`);
    }
    return bad;''',
            '''    if (scene.unknownPending !== null) {
      bad.push(`内核给了未知相位 ${scene.unknownPending}（UI 的 PENDING_SCENE 表没跟上）`);
    }
    if (this.injectedViolation !== null) bad.push(this.injectedViolation);
    return bad;''',
        ),
        (
            'sticky set after reconcile',
            '''      violations: this.reconcile(input, run, combat, scene),
    };''',
            '''      violations: this.reconcile(input, run, combat, scene),
    };
    // 第一次出现违约就**钉住**（粘性）。之后即使 `violations` 变空也不解冻。
    if (this.state.violations.length > 0 && this.frozenReason === null) {
      this.frozenReason = this.state.violations[0];
    }''',
        ),
        (
            'guard accessors',
            '''  /** 战斗 store（P2 的那一套原样复用：手势、动作表版本号、拒绝证明都在里面）。 */''',
            '''  /** 现在能不能改状态：`null` = 能；否则是"为什么不能"。 */
  frozen(): string | null {
    return this.frozenReason;
  }

  /**
   * 所有权威动作的统一入口检查。**每个** `RunStore` 动作方法都必须先过它。
   *
   * 返回 `false` 时还会留一条日志：玩家点了一个被冻结的按钮，界面上必须有痕迹
   * （静默无效就是 §4.22 那种"点了没反应"）。
   */
  private canMutate(what: string): boolean {
    if (this.frozenReason === null) return true;
    this.note(`界面已冻结，${what}被拒绝：${this.frozenReason}`, "bad");
    this.refresh();
    return false;
  }

  /**
   * 测试钩子：注入一条违约（`?debug` 下由探针调用）。
   *
   * 存在的理由：闸门 43 要**真的**把界面推进冻结态，而不是"读一遍代码相信它会冻结"。
   */
  injectViolation(text: string | null): void {
    this.injectedViolation = text;
    this.refresh();
  }

  /** 战斗 store（P2 的那一套原样复用：手势、动作表版本号、拒绝证明都在里面）。 */''',
        ),
        (
            'wire guard to game store',
            '''      this.combatStore = new GameStore(this.host);''',
            '''      this.combatStore = new GameStore(this.host);
      // 战斗动作是 `CombatScreen` 直接发的 ⇒ 冻结判据必须注入到那一层。
      this.combatStore.setDispatchGuard(() => this.frozenReason);''',
        ),
        (
            'clear on startRun',
            '''  startRun(seed: number, ascension: number): void {
    this.host.startRun(seed, ascension);''',
            '''  startRun(seed: number, ascension: number): void {
    // 新开一局是**唯一**的解除冻结途径（粘性，见 `frozenReason`）。
    this.frozenReason = null;
    this.injectedViolation = null;
    this.host.startRun(seed, ascension);''',
        ),
    ],
)
print('done')
