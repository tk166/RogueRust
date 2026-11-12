// 战斗前（`SC-03`）：站在战斗节点上，但**还没开打**。
//
// ## 为什么这一屏必须存在（而不是点了就自动开打）
//
// 1. plan 的硬要求：**战斗开始由权威 API 决定，不靠 UI mode**。这一屏的存在本身就是证据 ——
//    它由 `rd_run_in_fight() == 0 && pending == 0 && 这一格会开战` 算出来（`run/scene.ts`），
//    而不是"点了按钮所以进入战斗"。
// 2. 玩家需要**看到要打谁**再决定（这里是 StS 也有的"进入战斗"确认）。
// 3. 如果开战被内核拒绝（比如相位不对），这一屏还在，玩家能看到原因 —— 自动开打的话
//    就变成"点了一下，什么都没发生"（§4.22 的死按钮）。
//
// ## 交互
//
// * 主按钮 "进入战斗"（唯一的推进方式）；
// * **没有"撤退"**：内核没有这条路，画一个不能用的按钮是骗人。所以给一句"这一格不能跳过"。
// * 遭遇名来自 `rd_run_encounter_id_*`，中文名走 i18n 的 monsters 表（缺条目就显示 id）。

import { displayName } from "../../i18n/index.js";

export interface PreCombatSceneProps {
  readonly encounter: string;
  readonly kind: number;
  readonly kindLabel: string;
  readonly floor: number;
  readonly heroHp: number;
  readonly heroHpMax: number;
  readonly ascension: number;
  readonly onBegin: () => void;
  readonly busy?: boolean;
}

export function PreCombatScene({
  encounter,
  kindLabel,
  floor,
  heroHp,
  heroHpMax,
  ascension,
  onBegin,
  busy = false,
}: PreCombatSceneProps) {
  const name = encounter ? displayName("monsters", encounter) : "未知遭遇";
  return (
    <section className="scene scene-precombat" data-scene="SC-03">
      <header className="scene-head">
        <h2>{kindLabel}</h2>
        <p className="scene-sub">第 {floor} 层{ascension > 0 ? ` · 进阶 ${ascension}` : ""}</p>
      </header>

      <div className="precombat-card" data-encounter={encounter}>
        <div className="precombat-name">{name}</div>
        {encounter && <div className="precombat-id muted">{encounter}</div>}
        <div className="precombat-hp">
          你的生命 <b>{heroHp}</b> / {heroHpMax}
        </div>
      </div>

      <button type="button" className="primary" data-fight-begin onClick={onBegin} disabled={busy}>
        {busy ? "正在开始…" : "进入战斗"}
      </button>
      <p className="scene-foot muted">这一格不能跳过：打过去才能继续往上。</p>
    </section>
  );
}
