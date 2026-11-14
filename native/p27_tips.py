"""§379：奖励屏 / 商店接上悬浮详情（`CardTip`）。

两个屏各自维护一个"现在指着哪一件"（`hover`），因为它们是**不同的场景**，
状态不该跨屏活着（切屏就没了，这是对的）。

奖励屏：三张候选牌 + 药水 + 遗物，都能指。
商店：四排货架（有色牌 / 遗物 / 药水 / 无色牌）+ 价格作为 note。

⚠️ 触摸上**不拦点击**：`onPointerDown` 只负责"把详情亮出来"，`onClick` 照旧买/拿。
"""

import io

# ── 1. RewardScene ─────────────────────────────────────────────────────────
PATH = 'web-next/src/run/scenes/RewardScene.tsx'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''import { Badge } from "../../assets/Badge.js";
import { badgeLook } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";'''
NEW = '''import { useState } from "react";
import { Badge } from "../../assets/Badge.js";
import { badgeLook } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { CardTip, type TipRequest } from "../overlays/CardTip.js";'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''  onTakeRelic,
  onSkip,
}: RewardSceneProps) {
  return ('''
NEW = '''  onTakeRelic,
  onSkip,
}: RewardSceneProps) {
  // §379：指着哪一件。**一个**状态就够 —— 详情面板只有一个。
  const [tip, setTip] = useState<TipRequest | null>(null);
  /** 三个事件处理器用同一套：鼠标移入 / 键盘聚焦 / 触摸按下都亮详情。 */
  const tipProps = (request: TipRequest) => ({
    onPointerEnter: () => setTip(request),
    onFocus: () => setTip(request),
    onPointerDown: () => setTip(request),
  });
  return ('''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# 药水 / 遗物行：加 tip
OLD = '''          <div className="reward-row" data-reward-potion={potion}>'''
NEW = '''          <div
            className="reward-row"
            data-reward-potion={potion}
            {...tipProps({ kind: "potion", id: potion })}
          >'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''          <div className="reward-row" data-reward-relic={relic}>'''
NEW = '''          <div
            className="reward-row"
            data-reward-relic={relic}
            {...tipProps({ kind: "relic", id: relic })}
          >'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''            data-reward-card-id={card.id}
            disabled={busy}
            onClick={() => onTakeCard(card.slot)}
          >'''
NEW = '''            data-reward-card-id={card.id}
            disabled={busy}
            {...tipProps({ kind: "card", id: card.id })}
            onClick={() => onTakeCard(card.slot)}
          >'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# 面板 + 关闭：离开屏就没了（组件卸载），所以不需要额外清理。
OLD = '''      <button type="button" className="primary" data-reward-skip disabled={busy} onClick={onSkip}>
        领完了 · 继续
      </button>'''
NEW = '''      <CardTip request={tip} />

      <button type="button" className="primary" data-reward-skip disabled={busy} onClick={onSkip}>
        领完了 · 继续
      </button>'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('RewardScene: CardTip')

# ── 2. ShopScene ───────────────────────────────────────────────────────────
PATH = 'web-next/src/run/scenes/ShopScene.tsx'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''import { Badge } from "../../assets/Badge.js";
import { badgeLook, type BadgeKind } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { removalUsable, type ShelfRow } from "../models.js";'''
NEW = '''import { useState } from "react";
import { Badge } from "../../assets/Badge.js";
import { badgeLook, type BadgeKind } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { removalUsable, type ShelfRow } from "../models.js";
import { CardTip, type TipKind, type TipRequest } from "../overlays/CardTip.js";'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''function shelfName(kind: ShopShelfView["kind"], id: string): string {'''
NEW = '''/** 货架 → 详情面板的种类（`colorless` 也是卡）。 */
function tipKindOf(kind: ShopShelfView["kind"]): TipKind {
  switch (kind) {
    case "card":
    case "colorless":
      return "card";
    case "relic":
      return "relic";
    default:
      return "potion";
  }
}

function shelfName(kind: ShopShelfView["kind"], id: string): string {'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''  const canRemove = removalUsable(removalAvailable, removePrice, gold);
  return ('''
NEW = '''  const canRemove = removalUsable(removalAvailable, removePrice, gold);
  // §379：商店里"这张牌是什么"只能靠名字猜 —— 现在指着就显示费用/稀有度/规则。
  const [tip, setTip] = useState<TipRequest | null>(null);
  return ('''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''                  data-affordable={row.affordable ? "1" : "0"}
                  disabled={busy || sold}
                  onClick={() => onBuy(shelf.kind, row.slot)}
                >'''
NEW = '''                  data-affordable={row.affordable ? "1" : "0"}
                  disabled={busy || sold}
                  // §379：指着/按住就亮详情。**不拦 click** —— 点一下仍然直接买（触屏也一样）。
                  onPointerEnter={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }
                  onFocus={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }
                  onPointerDown={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }
                  onClick={() => onBuy(shelf.kind, row.slot)}
                >'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''      <button type="button" className="primary" data-shop-leave onClick={onLeave} disabled={busy}>
        离开商店
      </button>'''
NEW = '''      <CardTip request={tip} />

      <button type="button" className="primary" data-shop-leave onClick={onLeave} disabled={busy}>
        离开商店
      </button>'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('ShopScene: CardTip')
