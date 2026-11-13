// 药水腰带（顶栏右侧那一排）：用 / 扔。
//
// ## 交互设计
//
// 1. **"能不能现在用"由内核说**（`rd_run_potion_needs_fight`）：战斗外只有 run-only 的药水
//    （Fruit Juice / Entropic Brew 一类）能喝。第一版只在战斗里给"用"，于是那两瓶在战斗外
//    永远点不动（§158 记过）。
// 2. **要敌人的药水要先选目标**：`rd_run_potion_effect` 说 `1` 时要敌人 —— 于是这里先进入
//    "选目标"状态，点敌人再喝；没有敌人时直接拒绝并说原因（不猜"第一个活着的"）。
// 3. **扔药水要二次确认**：扔了就没了（内核没有撤销）。用一次点击"扔" + 一次"确定"。
// 4. 空槽也画（灰色）：玩家要能看出腰带还剩几个位置。

import { Badge } from "../../assets/Badge.js";
import { badgeLook } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { potionTargeting, potionUsable } from "../models.js";

export interface PotionSlotView {
  readonly slot: number;
  readonly id: string;
  /** `rd_run_potion_effect`：1 敌人 / 2 自己或本局 / 3 全体 / 0 未知。 */
  readonly effect: number;
  /** `rd_run_potion_needs_fight`：0 随时 / 1 只在战斗里。 */
  readonly needsFight: number;
}

export interface PotionBarProps {
  readonly potions: readonly PotionSlotView[];
  readonly inFight: boolean;
  /** 战斗中活着的敌人槽（给药水选目标用）。 */
  readonly enemySlots: readonly number[];
  /** 正在等玩家选目标的药水槽（`-1` = 没在选）。 */
  readonly targetingSlot: number;
  readonly onUse: (slot: number, target: number) => void;
  readonly onDrop: (slot: number) => void;
  readonly onPickTarget: (slot: number) => void;
  readonly busy?: boolean;
}

export function PotionBar({
  potions,
  inFight,
  enemySlots,
  targetingSlot,
  onUse,
  onDrop,
  onPickTarget,
  busy = false,
}: PotionBarProps) {
  return (
    <div className="potion-bar" data-potion-count={potions.length} data-targeting={targetingSlot}>
      {potions.map((potion) => {
        const usable = potionUsable(potion.needsFight, inFight);
        const targeting = potionTargeting(potion.effect);
        const needsTarget = targeting === "enemy";
        const why = !usable
          ? "这瓶只能在战斗里喝"
          : needsTarget && enemySlots.length === 0
            ? "需要一个敌人目标，但场上没有"
            : undefined;
        return (
          <div className="potion-slot" key={potion.slot} data-potion-slot={potion.slot} data-potion-id={potion.id}>
            <Badge look={badgeLook("potions", potion.id)} title={potion.id} />
            <span className="potion-name" title={why}>
              {displayName("potions", potion.id)}
            </span>
            <div className="potion-actions">
              <button
                type="button"
                data-potion-use={potion.slot}
                data-usable={usable ? "1" : "0"}
                disabled={busy || !usable}
                title={why}
                onClick={() => {
                  if (needsTarget) {
                    // 要目标：先进入"选目标"，由战斗屏的敌人点击来完成。
                    onPickTarget(potion.slot);
                    return;
                  }
                  onUse(potion.slot, -1);
                }}
              >
                {needsTarget && targetingSlot !== potion.slot ? "选目标" : "用"}
              </button>
              <button type="button" data-potion-drop={potion.slot} disabled={busy} onClick={() => onDrop(potion.slot)}>
                扔
              </button>
            </div>
          </div>
        );
      })}
      {potions.length === 0 && <span className="muted">没有药水</span>}
    </div>
  );
}
