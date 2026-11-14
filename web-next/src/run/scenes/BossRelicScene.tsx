// 幕间（`SC-13`，§370）：**这一幕通关 + Boss 遗物三选一**。
//
// ## 为什么这两件事是同一屏
//
// StS 的节奏就是：打赢 Boss → 回满血 → 三选一 Boss 遗物 → 下一幕。内核已经做了前半段
// （`mark_boss_beaten` 换幕、回满血、生成新地图），三选一是它补的最后一环。所以这一屏
// 同时承担"幕通关"的叙事和"必须选一件"的动作 —— 分开成两屏会让玩家在两屏之间没事可做。
//
// ## 交互
//
// * **三件都画出来**（名字 + 素材徽章 + id），点一件即选走；
// * **没有"跳过"**：内核的三选一是这一屏的唯一出路（跳过等于不给遗物，StS 里不存在）；
// * 选走之后内核清空这一手，场景自动回到新一幕的地图 —— 界面不需要自己"跳到下一屏"。

import { Badge } from "../../assets/Badge.js";
import { badgeLook } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { tipHandlers } from "../overlays/tipStore.js";

export interface BossRelicSceneProps {
  /** 刚刚通关的幕数（1 起）。 */
  readonly clearedAct: number;
  /** 下一幕的幕数（= clearedAct + 1）。 */
  readonly nextAct: number;
  readonly relics: readonly string[];
  readonly onTake: (slot: number) => void;
  readonly busy?: boolean;
}

export function BossRelicScene({ clearedAct, nextAct, relics, onTake, busy = false }: BossRelicSceneProps) {
  return (
    <section className="scene scene-boss-relic" data-scene="SC-13" data-relic-count={relics.length}>
      <header className="scene-head">
        <h2>第 {clearedAct} 幕通关</h2>
        <p className="scene-sub">
          生命已回满 · 下一幕是第 {nextAct} 幕 · 先挑一件 Boss 遗物
        </p>
      </header>

      <div className="boss-relic-list" data-boss-relic-options={relics.length}>
        {relics.map((id, slot) => (
          <button
            key={`${slot}-${id}`}
            type="button"
            className="boss-relic"
            data-boss-relic={slot}
            data-boss-relic-id={id}
            disabled={busy}
            // §404：Boss 遗物也要有悬浮详情（玩家报的"boss 奖励界面遗物没有悬浮窗"）。
            // 面板由外壳统一画（§389 的唯一宿主），这里只说"指的是哪一件"。
            {...tipHandlers({ kind: "relic", id })}
            onClick={() => onTake(slot)}
          >
            <Badge look={badgeLook("relics", id)} size="md" title={id} />
            <span className="boss-relic-name">{displayName("relics", id)}</span>
            <span className="boss-relic-id muted">{id}</span>
          </button>
        ))}
        {relics.length === 0 && <p className="muted">没有待选的遗物（内核没给）。</p>}
      </div>

      <p className="scene-foot muted">必须选一件才能继续：Boss 遗物是这一幕的收尾。</p>
    </section>
  );
}
