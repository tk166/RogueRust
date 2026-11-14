// 二维素材的**渲染**：两位大写字母 + 调色板（卡面 / 遗物 / 药水 / 状态共用）。
//
// ## 为什么是字母而不是图标
//
// 这一版要的是**流水线**，不是美术：字母徽章能把"每个 id 都有东西可画"这件事变得
// **可断言**（DOM 里真的有两个字符、颜色来自清单）。将来换成图标/立绘时，替换的是
// `Badge` 的内部实现，`registry.badgeLook()` 的接口不变。
//
// ## 可读性（沿用 P1 的结论）
//
// * 字号按容器自适应，但**最小 11px**（再小就只剩噪点）；
// * 字母用高对比描边（`paint-order: stroke`），因为调色板里有浅色（bone）；
// * `aria-label` 带上内容 id —— 屏幕阅读器与闸门都能读。

import type { BadgeLook, BadgeKind } from "./registry";

export interface BadgeProps {
  readonly look: BadgeLook;
  /** 尺寸档：`sm` 手牌/列表/顶栏，`md` 奖励/商店卡片，`lg` 卡牌详情。 */
  readonly size?: "sm" | "md" | "lg";
  /** 是否显示右下角的升级角标（`+`）。 */
  readonly upgraded?: boolean;
  readonly title?: string;
}

/** 各表的中文名（诊断与 aria 用）。 */
const KIND_LABEL: Record<BadgeKind, string> = {
  cards: "卡牌",
  relics: "遗物",
  potions: "药水",
  statuses: "状态",
};

export function Badge({ look, size = "sm", upgraded = false, title }: BadgeProps) {
  const px = size === "lg" ? 56 : size === "md" ? 34 : 22;
  return (
    <span
      className={`asset-badge asset-badge--${size}`}
      data-asset-badge={look.kind}
      data-asset-id={look.id}
      data-asset-letters={look.letters}
      aria-label={`${KIND_LABEL[look.kind]} ${title ?? look.id}（${look.letters}）`}
      title={title ?? look.id}
      style={{
        width: px,
        height: px,
        background: `linear-gradient(160deg, ${look.palette.body}, ${look.palette.accent})`,
        borderColor: look.palette.eye,
        fontSize: Math.max(11, Math.round(px * 0.42)),
      }}
    >
      <span className="asset-badge__letters" style={{ color: look.palette.eye }}>
        {look.letters}
      </span>
      {upgraded && (
        <span className="asset-badge__plus" aria-hidden>
          +
        </span>
      )}
    </span>
  );
}
