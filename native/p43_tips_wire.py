"""§389：把所有"指一下就该显示详情"的地方接到**同一个**面板上。

六处：遗物条 / 药水腰带 / 手牌（3D 文字层）/ 状态 chip / 奖励屏 / 商店 / 牌组选择器。
面板宿主只有一个（`RunApp` 的 subbar 之后 = 药水栏下方、战场上方）。

同时做 §390（玩家报的第 7 条）：牌组选择器（删卡 / 锻造 / 抽烟斗）也要
**二维卡面 + 中文名 + 悬浮详情**，而且**每一行等宽**（现在"名字 + id"长度不齐，右边参差）。
"""

import io


def patch(path, pairs, label):
    t = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert t.count(old) == 1, '%s: %r (%d)' % (label, old[:60], t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', label)


# ── 1. RunApp：挂宿主 + 遗物条接上 tip ─────────────────────────────────────
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'import { PotionBar } from "./overlays/PotionBar";',
            'import { PotionBar } from "./overlays/PotionBar";\n'
            'import { CardTipHost } from "./overlays/CardTip";\n'
            'import { tipHandlers } from "./overlays/tipStore.js";',
        ),
        (
            '''              <span className="relic-chip" key={`${id}-${index}`} data-relic-id={id} title={id}>''',
            '''              <span
                className="relic-chip"
                key={`${id}-${index}`}
                data-relic-id={id}
                title={id}
                {...tipHandlers({ kind: "relic", id })}
              >''',
        ),
        (
            '''      {/* ── 幕间幕布（§2.3）：纯演出，不挡操作 ─────────────────────────────── */}''',
            '''      {/*
        §389：**唯一那个**详情面板。挂在这里 = 药水栏下方、战场上方（玩家点名要的位置）。
        六个调用点都只调 `showTip()`，所以不可能同时出现两个面板。
      */}
      <CardTipHost />

      {/* ── 幕间幕布（§2.3）：纯演出，不挡操作 ─────────────────────────────── */}''',
        ),
    ],
    'RunApp',
)

# ── 2. 药水腰带：接上 tip ──────────────────────────────────────────────────
patch(
    'web-next/src/run/overlays/PotionBar.tsx',
    [
        (
            'import { potionTargeting, potionUsable } from "../models.js";',
            'import { potionTargeting, potionUsable } from "../models.js";\n'
            'import { tipHandlers } from "./tipStore.js";',
        ),
        (
            '''          <div className="potion-slot" key={potion.slot} data-potion-slot={potion.slot} data-potion-id={potion.id}>''',
            '''          <div
            className="potion-slot"
            key={potion.slot}
            data-potion-slot={potion.slot}
            data-potion-id={potion.id}
            {...tipHandlers({ kind: "potion", id: potion.id })}
          >''',
        ),
    ],
    'PotionBar',
)

# ── 3. 奖励屏 / 商店：改用 store（面板由外壳统一画）───────────────────────
patch(
    'web-next/src/run/scenes/RewardScene.tsx',
    [
        (
            '''import { CardTip, type TipRequest } from "../overlays/CardTip.js";''',
            '''import { showTip, tipHandlers, type TipRequest } from "../overlays/tipStore.js";''',
        ),
        (
            '''  // §379：指着哪一件。**一个**状态就够 —— 详情面板只有一个。
  const [tip, setTip] = useState<TipRequest | null>(null);
  /** 三个事件处理器用同一套：鼠标移入 / 键盘聚焦 / 触摸按下都亮详情。 */
  const tipProps = (request: TipRequest) => ({
    onPointerEnter: () => setTip(request),
    onFocus: () => setTip(request),
    onPointerDown: () => setTip(request),
  });''',
            '''  // §389：面板由外壳统一画（`CardTipHost`），这里只负责"指哪一件"。
  const tipProps = (request: TipRequest) => tipHandlers(request);''',
        ),
        ('      <CardTip request={tip} />\n\n', ''),
        ('import { useState } from "react";\n', ''),
    ],
    'RewardScene',
)

patch(
    'web-next/src/run/scenes/ShopScene.tsx',
    [
        (
            '''import { CardTip, type TipKind, type TipRequest } from "../overlays/CardTip.js";''',
            '''import { showTip, tipHandlers, type TipKind, type TipRequest } from "../overlays/tipStore.js";''',
        ),
        (
            '''  // §379：商店里"这张牌是什么"只能靠名字猜 —— 现在指着就显示费用/稀有度/规则。
  const [tip, setTip] = useState<TipRequest | null>(null);''',
            '''  // §389：面板由外壳统一画，这里只负责"指哪一件"。
  const tip = (request: TipRequest) => tipHandlers(request);''',
        ),
        (
            '''                  // §379：指着/按住就亮详情。**不拦 click** —— 点一下仍然直接买（触屏也一样）。
                  onPointerEnter={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }
                  onFocus={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }
                  onPointerDown={() =>
                    setTip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })
                  }''',
            '''                  // §379：指着/按住就亮详情。**不拦 click** —— 点一下仍然直接买（触屏也一样）。
                  {...tip({ kind: tipKindOf(shelf.kind), id: row.id, note: sold ? "已售出" : `${row.price} ◈` })}''',
        ),
        ('      <CardTip request={tip} />\n\n', ''),
        ('import { useState } from "react";\n', ''),
    ],
    'ShopScene',
)

# ── 4. 牌组选择器：二维卡面 + 中文名 + 悬浮详情 + 等宽（§390）─────────────
patch(
    'web-next/src/run/overlays/DeckSelectOverlay.tsx',
    [
        (
            '''import { displayName } from "../../i18n/index.js";
import { deckPickAllowed, deckPickCopy, type DeckPickPurpose } from "../models.js";''',
            '''import { Badge } from "../../assets/Badge.js";
import { badgeLook } from "../../assets/registry.js";
import { displayName } from "../../i18n/index.js";
import { deckPickAllowed, deckPickCopy, type DeckPickPurpose } from "../models.js";
import { tipHandlers } from "./tipStore.js";''',
        ),
        (
            '''                title={row.allowed ? undefined : "这张牌已经升级过了"}
                onClick={() => onPick(row.index)}
              >
                <span className="deck-select-index muted">{row.index + 1}</span>
                <span className="deck-select-name">{row.name}</span>
                <span className="deck-select-id muted">{row.id}</span>
                {!row.allowed && <span className="deck-select-why">已升级</span>}''',
            '''                title={row.allowed ? undefined : "这张牌已经升级过了"}
                // §389/§390：指着就显示"种类 · 费用 · 稀有度 + 规则"（与商店/奖励同一个面板）。
                {...tipHandlers({ kind: "card", id: row.id })}
                onClick={() => onPick(row.index)}
              >
                <span className="deck-select-index muted">{row.index + 1}</span>
                {/* §390：二维卡面（两位字母 + 调色板），与商店/奖励同一张素材表。 */}
                <Badge
                  look={badgeLook("cards", row.id)}
                  size="sm"
                  upgraded={row.id.endsWith("+")}
                  title={row.id}
                />
                <span className="deck-select-name">{row.name}</span>
                {!row.allowed && <span className="deck-select-why">已升级</span>}''',
        ),
    ],
    'DeckSelectOverlay',
)
