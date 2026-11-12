// P4 之前**还没做界面**的场景（商店/篝火/宝箱/事件/选牌…）。
//
// ## 为什么不是一个空白页，也不是"自动跳过"
//
// 1. **空白页**会让玩家以为卡住了（§4.22 的死按钮）。
// 2. **自动跳过**更糟：玩家会发现自己"路过了商店但什么都没看见"，而日志里也没有痕迹 ——
//    这等于 UI 偷偷替玩家做了决定。
// 3. 所以：**明说**这一屏是什么、还没做，并给一个**确实会推进**的按钮（"用内核的默认动作通过"）。
//    那个动作是 `RunStore.settleDefault()`，它在日志里留一行"用默认动作通过了相位 N"。
//
// 这一屏的存在本身是**进度证据**：P4 做完哪一屏，这里就少一行。

import type { SceneId } from "../scene.js";

export interface UnsupportedSceneProps {
  readonly scene: SceneId;
  readonly label: string;
  /** 这一屏的相位号（`rd_run_pending`），日志与诊断都对得上。 */
  readonly pending: number;
  readonly onSettle: () => void;
  readonly detail?: string;
}

/** 每一屏"还没做什么"的一句话（写给玩家，也写给下一个接手的自己）。 */
const WHAT_IS_MISSING: Partial<Record<SceneId, string>> = {
  "SC-01b": "祝福里的「从牌组删/升级/变形一张」需要牌组选择器",
  "SC-05": "商店的四排货架（卡牌/遗物/药水/删牌）与定价",
  "SC-06": "篝火的「休息 / 锻造」两个选项",
  "SC-07": "宝箱的开箱演出与遗物三选一",
  "SC-08": "事件的正文、选项与分支",
  "SC-09": "事件里的「从牌组选一张」",
  "SC-10": "事件的候选三选一",
};

export function UnsupportedScene({ scene, label, pending, onSettle, detail }: UnsupportedSceneProps) {
  return (
    <section className="scene scene-unsupported" data-scene={scene} data-pending={pending}>
      <header className="scene-head">
        <h2>{label}</h2>
        <p className="scene-sub">这一屏的界面还没做（计划 P4）</p>
      </header>
      <p className="scene-note">
        {detail ?? WHAT_IS_MISSING[scene] ?? "这一屏还没有对应的界面"}
      </p>
      <p className="scene-note muted">
        内核已经停在这一屏（相位 {pending}），所以它**不是** bug —— 只是还没有画。
      </p>
      <button type="button" className="primary" data-settle-default onClick={onSettle}>
        用内核的默认动作通过
      </button>
      <p className="scene-foot muted">
        按下去会用内核给的默认动作结算这一屏，并在日志里留一行记录。
      </p>
    </section>
  );
}
