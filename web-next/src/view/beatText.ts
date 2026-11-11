// beat → 一行中文。**演出层的唯一文案来源**（不再靠观察向量 diff 猜发生了什么）。
//
// 为什么值得接 beat：观察向量 diff 只能告诉你"净变化"（敌人 -6 血），说不出"打了两下、每下 3"、
// 也说不出"伤害被格挡了 4"。beat 是内核自己的叙述，13 种 kind 编号是 ABI。
//
// ⚠️ 这里出现的 `def` 是**定义 id**（`standard.strength` / `bash`），不是本地化名字。
// 卡名与状态名统一本地化是后续的事（用户已明确：卡名与美术一起处理）。

import { BEAT, type Beat } from "../wasm/snapshot";
import { displayName } from "../i18n";

/** 墙位槽 → 人话。`-1` 英雄、`0..5` 敌人、`-2` 没有。 */
function who(slot: number): string {
  if (slot === -1) return "你";
  if (slot === -2) return "无";
  return `敌人 ${slot}`;
}

function statusName(def: string): string {
  // `standard.vulnerable` → 易伤（i18n 表）；没条目时回退成 `vulnerable`。
  return displayName("statuses", def);
}

/** 一条 beat 的文案；返回 `null` 表示"这条不用给玩家看"。 */
export function beatText(beat: Beat): string | null {
  switch (beat.kind) {
    case BEAT.cardPlayed:
      // `beat.def` 是**定义 id**（`bash` / `strike+`）⇒ 走 i18n 表拿中文名。
      return `打出 ${beat.def ? displayName("cards", beat.def) : "一张牌"}`;
    case BEAT.damage: {
      const blocked = beat.b > 0 ? `（格挡 ${beat.b}）` : "";
      return `${who(beat.target)} −${beat.a} 血${blocked}`;
    }
    case BEAT.block:
      return `${who(beat.target)} +${beat.a} 格挡`;
    case BEAT.heal:
      return `${who(beat.target)} +${beat.a} 血`;
    case BEAT.statusChanged:
      return `${who(beat.target)} ${statusName(beat.def)} +${beat.a}`;
    case BEAT.statusRemoved:
      return `${who(beat.target)} ${statusName(beat.def)} 清除`;
    case BEAT.statusPrevented:
      return `${who(beat.target)} ${statusName(beat.def)} 被挡下`;
    case BEAT.downed:
      return `${who(beat.target)} 倒下`;
    case BEAT.escaped:
      return `${who(beat.target)} 逃走了`;
    case BEAT.summoned:
      return `${who(beat.target)} 召唤了 ${beat.def || "敌人"}`;
    case BEAT.destroyed:
      return `${who(beat.target)} 被摧毁`;
    case BEAT.turnStarted:
      return `${who(beat.actor)} 回合开始`;
    case BEAT.turnEnded:
      return `${who(beat.actor)} 回合结束`;
    default:
      return null;
  }
}

/**
 * 一组 beat 的摘要。
 *
 * `dropped > 0` 时**必须**说出来：那是"内核丢了演出记录"，玩家看到的不是全貌（§纪律：
 * 降级要可见，不能假装完整）。
 */
export function describeBeats(beats: readonly Beat[], dropped: number): string {
  const lines = beats.map(beatText).filter((line): line is string => line !== null);
  const summary = lines.slice(0, 3).join(" · ");
  if (dropped > 0) {
    return `${summary || "（无演出）"} · ⚠️ 有 ${dropped} 条演出被丢弃`;
  }
  return summary;
}
