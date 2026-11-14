// 卡面文字：**DOM 覆盖层**，不是 3D 文字。
//
// 这是 P1 要回答的问题之一（plan §13 / 第十二轮 Review D3）：中文能不能在 390×844 上读出来。
// 结论与数字见 `docs/ui-next-p1.md`，代码这一侧的选择是：
//
//   * 3D 文字需要一份**中文字形图集**（子集化后仍有几十 KB 到几百 KB，且要跟着内容变化重建）；
//   * DOM 文字用系统字体，**0 字节**，任何字号都清晰，还能被浏览器选中/缩放。
//
// 所以：**牌身是 3D 的（跟着透视、拖拽、遮挡），文字是 DOM 的（永远正面朝屏幕）**。
// 位置由 `layout`（3D 侧每帧投影出来的屏幕坐标）驱动，所以文字始终贴在牌上。

import { useEffect, useRef } from "react";
import { Badge } from "../assets/Badge";
import { badgeLook } from "../assets/registry";
import { layout } from "../stage/layout";
import type { CombatView, ViewCard } from "../view/combatView";

/** 三档字号：手牌态只显示标题，选中态显示规则，详情态放大。数字写死是为了让闸门能断言。 */
export const TYPE_SCALE = {
  hand: { title: 11, rules: 0 },
  selected: { title: 15, rules: 12 },
  detail: { title: 20, rules: 14 },
} as const;

/**
 * 一张牌在屏幕上窄于这个像素数时，**标题会被藏起来，只留费用数字**。
 *
 * 这是 P1 最重要的一条实测结论（见 `docs/ui-next-p1.md`）：390×844 上 10 张牌并排时，
 * 每张只有约 19px 的可视条 —— 塞不下任何中文标题。与其把 11px 的字压成 6px（读不了），
 * 不如只显示**一个数字**（永远读得出），把"读牌"这件事交给选中放大与详情。
 * StS 手机版是同一个取舍。
 */
export const COMPACT_BELOW_PX = 44;

export interface TextOverlayProps {
  scene: CombatView;
  liftedSlot: number;
  /** [P1-UX] 仅桌面 hover；触屏通过按压/长按进入大卡预览。 */
  hoverCardSlot: number;
  /** 详情态：被点开的牌（显示完整规则），`-1` 表示没有。 */
  detailSlot: number;
  /** 模态是否打开（打开时覆盖层不显示手牌文字，避免和模态抢注意力）。 */
  modalOpen: boolean;
  /** [P1-UX] 详情可通过可见按钮关闭。 */
  onCloseDetail: () => void;
}

export function TextOverlay({ scene, liftedSlot, hoverCardSlot, detailSlot, modalOpen, onCloseDetail }: TextOverlayProps) {
  const layerRef = useRef<HTMLDivElement>(null);

  // rAF 循环：读 `layout`，直接改 style。**不经过 React**（60Hz 重渲染会把 P1 的 FPS 数字毁掉）。
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const layer = layerRef.current;
      if (!layer) return;
      const bySlot = new Map(layout.cards.map((card) => [card.slot, card]));
      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-card]"))) {
        const slot = Number(node.dataset.card);
        const screen = bySlot.get(slot);
        if (!screen) continue;
        const compact = screen.visibleW < COMPACT_BELOW_PX && !screen.lifted;
        // ⚠️ 锚点：紧凑态用 `hitX`（**露出来那条**的中心），不是牌心。
        // 叠放顺序是右压左，牌心可能被右邻盖住 —— 文字放牌心等于把费用数字塞到邻居底下。
        // 展开/抬起时整张牌都露着（`visibleW === w`，此时 hitX === x），用哪个都一样。
        const anchorX = compact ? screen.hitX : screen.x;
        node.style.transform = `translate3d(${anchorX}px, ${screen.y}px, 0) translate(-50%, -50%)`;
        // 文字框宽度取两者的小值（见 `CardScreen.visibleW` / `faceW`）：
        // 紧凑态受"露出来的那条"限制，抬起/悬停受"牌面看起来多宽"限制。
        node.style.width = `${Math.min(screen.faceW, screen.visibleW)}px`;
        node.style.height = `${screen.h}px`;
        // 与 3D 侧的 per-card renderOrder 对齐：抬起 > hover > 静止（否则牌上去了文字还在下面）。
        node.style.zIndex = String(screen.lifted ? 30 : slot === hoverCardSlot ? 25 : 10 + slot);
        // 窄到放不下标题 ⇒ 只留费用（闸门读这个 class 来断言"要么读得到、要么明确收起"）。
        node.classList.toggle("is-compact", compact);
      }
      // 提示条的位置也来自同一个纯函数（`regions.hudBottom`）：CSS 只消费变量，
      // 于是"气泡压 HUD"在结构上不可能再发生（两份认识 → 一份）。
      if (layout.regions) {
        document.documentElement.style.setProperty(
          "--hint-top",
          `${Math.round(layout.regions.hudBottom + 6)}px`
        );
      }
      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-enemy]"))) {
        const slot = Number(node.dataset.enemy);
        const enemy = layout.enemies.find((candidate) => candidate.slot === slot);
        if (!enemy) continue;
        node.style.transform = `translate3d(${enemy.x}px, ${enemy.y - enemy.r - 22}px, 0) translate(-50%, -50%)`;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="text-layer" ref={layerRef} aria-hidden={modalOpen}>
      {scene.hand.map((card, index) => {
        const selected = index === liftedSlot;
        const hovered = index === hoverCardSlot;
        // 手牌态：只有标题（StS 手机版就是这个取舍）；选中态：标题 + 规则。
        const showRules = selected && detailSlot < 0;
        return (
          <div
            key={`${card.id}-${index}`}
            className={`card-text${selected ? " is-selected" : ""}${hovered ? " is-hovered" : ""}`}
            data-card={index}
            data-kind={card.kind}
          >
            <div className="card-text__cost" style={{ fontSize: `${selected ? 14 : 11}px` }}>
              {card.cost}
            </div>
            {/*
              卡面素材（`assets/registry.ts` 的流水线产物）：两位字母 + 调色板。
              ⚠️ 查表用 `card.defId`（**内容 id**），不是 `card.id` —— 后者是
              `hand-<slot>-<defSlot>` 这种合成 id，查表会走降级。
              紧凑态（窄屏只剩费用数字）由 CSS 收起。
            */}
            <div className="card-text__art" data-card-art>
              <Badge
                look={badgeLook("cards", card.defId)}
                size={selected ? "md" : "sm"}
                upgraded={card.defId.endsWith("+")}
                title={card.defId}
              />
            </div>
            <div
              className="card-text__title"
              data-title
              style={{ fontSize: `${selected ? TYPE_SCALE.selected.title : TYPE_SCALE.hand.title}px` }}
            >
              {card.name}
            </div>
            {showRules && (
              <div
                className="card-text__rules"
                data-rules
                style={{ fontSize: `${TYPE_SCALE.selected.rules}px` }}
              >
                {card.rules}
              </div>
            )}
          </div>
        );
      })}

      {scene.enemies.map((enemy) => (
        <div key={enemy.id} className="enemy-label" data-enemy={enemy.slot}>
          <span className="enemy-label__name">{enemy.name}</span>
          <span className="enemy-label__hp">
            {enemy.hp}/{enemy.hpMax}
          </span>
          <span className="enemy-label__intent">{enemy.intent}</span>
        </div>
      ))}

      {/* 详情态：被点开的牌放大到可读尺寸（这是"能不能读完整描述"的那一档） */}
      {detailSlot >= 0 && <DetailCard card={scene.hand[detailSlot]} onClose={onCloseDetail} />}
    </div>
  );
}

function DetailCard({ card, onClose }: { card: ViewCard; onClose: () => void }) {
  return (
    <div className="detail-card">
      {/* [P1-UX] 触屏与键盘用户可见的关闭入口，不依赖探针。 */}
      <button type="button" className="detail-card__close" onClick={onClose} aria-label="关闭卡牌详情">×</button>
      {/* 详情态：卡面素材放在"立绘"的位置（这一档是给人看清"这张牌长什么样"的）。 */}
      <div className="detail-card__art" data-detail-art>
        <Badge look={badgeLook("cards", card.defId)} size="lg" upgraded={card.defId.endsWith("+")} title={card.defId} />
      </div>
      <div className="detail-card__title" style={{ fontSize: `${TYPE_SCALE.detail.title}px` }} data-detail-title>
        {card.name}
      </div>
      <div className="detail-card__cost">费用 {card.cost}</div>
      <div className="detail-card__rules" style={{ fontSize: `${TYPE_SCALE.detail.rules}px` }} data-detail-rules>
        {card.rules}
      </div>
    </div>
  );
}
