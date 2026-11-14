// 悬浮详情（§379）：**一个组件，四处复用**（奖励屏 / 商店 / 牌组 / 事件候选）。
//
// ## 玩家报的是什么
//
// "商店和奖励界面每个卡片没有跟随鼠标或者触摸的悬浮窗提示卡牌的具体内容，怎么选全靠盲猜。"
//
// 之前奖励屏只有 `名字 + 内容 id`，商店只有 `名字 + 价格`。而"这张牌 3 费打 32"与
// "这张牌 1 费打 6"是完全不同的决策 —— 名字读不出来。
//
// ## 两条交互（鼠标 / 触摸各一条，不互相顶）
//
// * **鼠标**：`pointerenter` 就显示（跟随到固定面板，不做"跟着光标飘"的浮窗 ——
//   贴边时飘窗会被裁掉，而且它会盖住相邻的牌，反而更难选）。
// * **触摸**：`pointerdown` 显示。⚠️ 触摸上**不**阻止点击 —— 商店的"点一下买"必须保留，
//   所以触摸是"按住不放看详情、松手仍然买"。真正不想买的人可以按住再移开（浏览器会取消 click）。
//
// ## 为什么是固定面板而不是 tooltip
//
// 固定面板的位置可预测、可断言（`data-card-tip`），也不会被容器裁掉。StS 手机版也是
// "点一下弹一张大卡"。像素位置交给 CSS，闸门只断言**内容**（名字/费用/稀有度/规则都在）。

// 悬浮详情（§379）：**一个组件，多处复用**（奖励屏 / 商店 / 选牌弹窗 / 牌组）。
//
// ## 玩家报的是什么
//
// "商店和奖励界面每个卡片没有跟随鼠标或者触摸的悬浮窗提示卡牌的具体内容，怎么选全靠盲猜。"
//
// ## 两条交互（鼠标 / 触摸各一条，不互相顶）
//
// * **鼠标**：`pointerenter` 就显示（固定面板，不做"跟着光标飘"的浮窗 ——
//   贴边时飘窗会被裁掉，而且它会盖住相邻的牌，反而更难选）。
// * **触摸**：`pointerdown` 显示。⚠️ 触摸上**不**阻止点击 —— 商店的"点一下买"必须保留，
//   所以触摸是"按住不放看详情、松手仍然买"。
//
// ## 分层（§384 修）
//
// 文案在 `view/cardTipText.ts`（**纯函数**，闸门直接编译它穷尽断言）；
// 本文件只是**渲染壳**（DOM + 事件）。所以"种类 · 费用 · 稀有度"只有一处算法。
//
// ## 为什么是固定面板而不是跟随光标的 tooltip
//
// 固定面板的位置可预测、可断言（`data-card-tip`），也不会被容器裁掉。
// ⚠️ 必须是 `position: fixed`（脱离文档流）：`sticky` 会撑动容器 ⇒ 卡牌重排 ⇒
// 鼠标下的牌换位置 ⇒ hover 换目标 ⇒ 面板换文字 ⇒ 死循环抖动（§381 实测）。

import { describeTip, type TipRequest } from "../../view/cardTipText.js";

export type { TipKind, TipRequest } from "../../view/cardTipText.js";

export interface CardTipProps {
  readonly request: TipRequest | null;
}

/**
 * 固定位置的详情面板。`request === null` 时**不渲染**（不留一个空盒子占位）。
 */
export function CardTip({ request }: CardTipProps) {
  if (!request) return null;
  const described = describeTip(request);
  return (
    <div
      className="card-tip"
      data-card-tip={request.id}
      data-tip-kind={request.kind}
      data-tip-title={described.title}
      data-tip-subtitle={described.subtitle}
      role="tooltip"
    >
      <div className="card-tip__head">
        <span className="card-tip__title" data-tip-title-text>
          {described.title}
        </span>
        {described.note && (
          <span className="card-tip__note" data-tip-note>
            {described.note}
          </span>
        )}
      </div>
      {described.subtitle && (
        <div className="card-tip__subtitle" data-tip-subtitle-text>
          {described.subtitle}
        </div>
      )}
      <div className="card-tip__body" data-tip-body>
        {described.body || "（这一条没有说明文本）"}
      </div>
    </div>
  );
}
