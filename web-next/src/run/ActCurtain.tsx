// 幕间幕布（`ui-state-model.md` §2.3）：换幕时的一屏演出。
//
// 旧页面（`web/index.html` 的 `#actCurtain`）就是这么做的：**纯演出**、1.6 秒自动淡出、
// 点一下也能关、**不需要任何新导出**（触发条件是 `rd_run_act()` 变大）。
//
// ## 为什么不挡操作
//
// 幕布是一层 `position: fixed` 的覆盖层。如果它吃掉指针事件，玩家在 1.6 秒里就"点不动" ——
// 而换幕之后**第一件该做的事**恰恰是点地图。所以：
// * 幕布本身 `pointer-events: none`（点击穿透）；
// * 只有"点一下继续"那一行是可点的（`pointer-events: auto`），点它 = 提前关掉；
// * 不点也会自己走 —— **幕布从不 gate 任何动作**。

export interface ActCurtainProps {
  /** 第几幕（`rd_run_act()`）。 */
  readonly act: number;
  /** 同一幕连开两局时也要能重播 ⇒ 用它当 React 的 key。 */
  readonly seq: number;
  /** 点一下 / 定时到 ⇒ 关掉。 */
  readonly onDismiss: () => void;
}

// 判定与时长在 `curtain.ts`（纯 `.ts`，闸门 48 在 Node 里直接导入 —— `.tsx` 会拖进 React）。
export { CURTAIN_MS, shouldShowCurtain } from "./curtain.js";

export interface ActCurtainProps {
  /** 第几幕（`rd_run_act()`）。 */
  readonly act: number;
  /** 同一幕连开两局时也要能重播 ⇒ 用它当 React 的 key。 */
  readonly seq: number;
  /** 点一下 / 定时到 ⇒ 关掉。 */
  readonly onDismiss: () => void;
}

export function ActCurtain({ act, seq, onDismiss }: ActCurtainProps) {
  return (
    <div
      className="act-curtain"
      data-act-curtain={act}
      data-act-curtain-seq={seq}
      // 覆盖层自己不吃事件；只有下面那行提示可点。
      onClick={onDismiss}
      role="presentation"
    >
      <div className="act-curtain-inner">
        <div className="act-curtain-act" data-act-curtain-label>
          第 {act} 幕
        </div>
        <div className="act-curtain-line">地图重画了 · 血量、牌组、遗物都带过来了</div>
        <div className="act-curtain-hint" data-act-curtain-hint>
          点一下继续（1.6 秒后自动关闭）
        </div>
      </div>
    </div>
  );
}
