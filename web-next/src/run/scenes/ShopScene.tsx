// 商店（`SC-05`，`pending == 2`）：四类货架 + 一次删卡服务。
//
// ## 交互设计
//
// 1. **价格只显示内核给的那一份**（`rd_run_shop_*_price` 已经算上会员卡/涨价）。页面自己算价
//    必然与内核漂，而"显示 100 却收 120"是最难查的那种 bug。
// 2. **买不起 ≠ 不可点**：买不起的按钮**能点**，点了给一句"金币不够（还差 N）"。禁用按钮
//    说不出差多少，玩家只能自己算。
// 3. **已售的货位保留位置**（`price < 0`）：整排忽然少一格会让玩家以为界面跳了。
// 4. **删卡服务每家店一次**（`§343`）：用 `removalAvailable()` 决定，不看"我买过没有"。
// 5. **离开永远可点**：商店不是必经关卡。

import { Badge } from "../../assets/Badge.js";
import { badgeLook, type BadgeKind } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { removalUsable, type ShelfRow } from "../models.js";

export interface ShopShelfView {
  readonly kind: "card" | "relic" | "potion" | "colorless";
  readonly title: string;
  readonly rows: readonly ShelfRow[];
}

export interface ShopSceneProps {
  readonly gold: number;
  readonly shelves: readonly ShopShelfView[];
  readonly removePrice: number;
  readonly removalAvailable: number;
  readonly onBuy: (kind: ShopShelfView["kind"], slot: number) => void;
  readonly onRemove: () => void;
  readonly onLeave: () => void;
  readonly busy?: boolean;
}

/** 货架 → 二维素材表（无色牌复用 `cards` 表：它也是卡）。 */
function badgeKindOf(kind: ShopShelfView["kind"]): BadgeKind {
  switch (kind) {
    case "card":
    case "colorless":
      return "cards";
    case "relic":
      return "relics";
    default:
      return "potions";
  }
}

function shelfName(kind: ShopShelfView["kind"], id: string): string {
  switch (kind) {
    case "card":
    case "colorless":
      return displayName("cards", id);
    case "relic":
      return displayName("relics", id);
    case "potion":
      return displayName("potions", id);
    default:
      return id;
  }
}

export function ShopScene({
  gold,
  shelves,
  removePrice,
  removalAvailable,
  onBuy,
  onRemove,
  onLeave,
  busy = false,
}: ShopSceneProps) {
  const canRemove = removalUsable(removalAvailable, removePrice, gold);
  return (
    <section className="scene scene-shop" data-scene="SC-05">
      <header className="scene-head">
        <h2>商店</h2>
        <p className="scene-sub">
          金币 {gold}
          {removalAvailable === 0 ? " · 这家店的删卡服务已经用过了" : ""}
        </p>
      </header>

      {shelves.map((shelf) => (
        <div className="shop-shelf" data-shelf={shelf.kind} key={shelf.kind}>
          <h3 className="shop-shelf-title">{shelf.title}</h3>
          <div className="shop-rows">
            {shelf.rows.map((row) => {
              const sold = !row.forSale;
              return (
                <button
                  key={row.slot}
                  type="button"
                  className={[
                    "shop-row",
                    sold ? "is-sold" : "",
                    !sold && !row.affordable ? "is-unaffordable" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  data-shop-buy={`${shelf.kind}:${row.slot}`}
                  data-price={row.price}
                  data-sold={sold ? "1" : "0"}
                  data-affordable={row.affordable ? "1" : "0"}
                  disabled={busy || sold}
                  onClick={() => onBuy(shelf.kind, row.slot)}
                >
                  <span className="shop-row-name">
                    {!sold && <Badge look={badgeLook(badgeKindOf(shelf.kind), row.id)} title={row.id} />}
                    {sold ? "已售出" : shelfName(shelf.kind, row.id)}
                  </span>
                  <span className="shop-row-price">
                    {sold ? "—" : `${row.price} ◈`}
                  </span>
                </button>
              );
            })}
            {shelf.rows.length === 0 && <p className="muted">这一排今天没货。</p>}
          </div>
        </div>
      ))}

      <div className="shop-service" data-shop-remove={removalAvailable}>
        <div>
          <h3 className="shop-shelf-title">删卡服务</h3>
          <p className="muted">
            {removalAvailable === 0
              ? "这家店已经用过了（每家店一次）"
              : `把一张牌永久移出牌组 · ${removePrice} 金币`}
          </p>
        </div>
        <button
          type="button"
          data-shop-remove-button
          disabled={busy || !canRemove}
          onClick={onRemove}
        >
          {removalAvailable === 0 ? "不可用" : canRemove ? "删一张牌" : "金币不够"}
        </button>
      </div>

      <button type="button" className="primary" data-shop-leave onClick={onLeave} disabled={busy}>
        离开商店
      </button>
    </section>
  );
}
