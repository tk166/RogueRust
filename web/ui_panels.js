// `RD_PANELS` -- **what the node panel should say and offer**, as pure data.
//
// Why this exists: `renderNode()` used to be a chain of `if (pending === ...)` blocks that each built
// their own HTML, so every new state meant editing a long chain (once in the wrong place), and none
// of it could be tested without a browser. Here each state is a branch of one function that takes a
// **plain snapshot** and returns a description:
//
//     describe(snapshot) -> { title, lines[], rows[], buttons[] }
//
// `index.html` renders that description and maps `button.action` onto one kernel call. Nothing in
// this file touches the DOM or the wasm, so `ui_test.mjs` can check every state with a literal
// snapshot -- which is the point: a new state is one case here plus one case there, and the page's
// HTML never changes shape.
//
// Loaded before `index.html`'s script; no build step (the whole web/ layer is zero-build).

const RD_PANELS = (() => {
  /// Effect code -> Chinese label. The kernel's closed vocabulary (`docs/port-plan.md` §80).
  const EFFECT_LABELS = ["", "回复", "金币", "受伤", "最大 HP", "什么也不做"];

  /// Kind number -> what to call it. Order is `run-layer.md` §7.2.
  const KIND_NAMES = ["", "战斗", "精英", "篝火", "商人", "未知", "宝箱", "Boss"];

  /// The effect phrase for an offer/choice half, or `""` when it does nothing.
  function effectText(code, amount) {
    if (code === 5 || code < 0) return "";
    return `${EFFECT_LABELS[code] || "?"} ${amount}`;
  }

  /// `blessing` / `friendly` / `danger` -- the page only chooses a CSS class from this.
  function tone(snapshot) {
    if (snapshot.cleared) return "good";
    if (snapshot.runOver) return "danger";
    return "";
  }

  function statsLine(s) {
    return (
      `floor ${s.floor} · hp ${s.hp}/${s.hpMax} · gold ${s.gold} · ` +
      `deck ${s.deckCount} · relics ${s.relicCount}`
    );
  }

  // ---------------------------------------------------------------------------------------------
  // The states, in the order they outrank each other. A state that is "more final" comes first:
  // a cleared act or a lost run outranks whatever the cursor happens to be standing on.
  // ---------------------------------------------------------------------------------------------
  function describeCleared(s) {
    return {
      title: `第 ${s.act} 幕通关 · ${s.bossName} 已击败`,
      tone: "good",
      lines: [statsLine(s)],
      rows: [],
      buttons: [
        { id: "again", label: "再打一局（同一 seed）", action: { kind: "restart" } },
        { id: "next", label: "换一个 seed", action: { kind: "next_seed" } },
      ],
    };
  }

  function describeOver(s) {
    return {
      title: `这一局结束了 · ${s.runOverWhy}`,
      tone: "danger",
      lines: [statsLine(s)],
      rows: [],
      buttons: [
        { id: "again", label: "再来一局（同一 seed）", action: { kind: "restart" } },
        { id: "next", label: "换一个 seed", action: { kind: "next_seed" } },
      ],
    };
  }

  function describeBlessing(s) {
    const buttons = (s.offers || []).map((offer, slot) => {
      const gain = effectText(offer.gain, offer.gainAmount);
      const cost = effectText(offer.cost, offer.costAmount);
      return {
        id: `blessing-${slot}`,
        label: offer.name,
        sub: cost === "" ? gain : `${gain}，代价 ${cost}`,
        action: { kind: "choose_start", slot },
      };
    });
    return {
      title: "塔底 · 选择一项祝福（选完才能出发）",
      lines: [],
      rows: [],
      buttons,
    };
  }

  function describeFight(s) {
    if (s.resolved) {
      return {
        title: "",
        lines: ["这个节点已结算 · 点亮的节点往前走"],
        rows: [],
        buttons: [],
      };
    }
    const name =
      s.kind === 7 ? `Boss · ${s.bossName}` : s.kind === 2 ? "精英节点（3 × Sentry）" : "战斗节点";
    return {
      title: name,
      lines: [],
      rows: [],
      buttons: [{ id: "fight", label: "开始战斗", action: { kind: "begin_fight" } }],
    };
  }

  function describeRest(s) {
    return {
      title: `篝火 · 回复 ${s.restHeal}`,
      lines: [],
      rows: [],
      buttons: [
        { id: "rest", label: "休息", action: { kind: "rest" } },
        { id: "smith", label: "打铁（选一张升级）", action: { kind: "smith" } },
        { id: "leave", label: "离开", action: { kind: "leave" } },
      ],
    };
  }

  function describeShop(s) {
    const rows = [];
    for (const [slot, card] of (s.shopCards || []).entries()) {
      rows.push({
        label: card.title || card.id,
        sub: card.chip,
        value: card.price < 0 ? "已售" : `${card.price} 金`,
        disabled: card.price < 0,
        // Shift+click shows the card (`port-plan.md` §95).
        card: `shop:${slot}`,
        button: { label: "买", action: { kind: "buy_card", slot } },
      });
    }
    for (const [slot, relic] of (s.shopRelics || []).entries()) {
      rows.push({
        label: relic.title || relic.id,
        sub: "",
        value: relic.price < 0 ? "已售" : `${relic.price} 金`,
        disabled: relic.price < 0,
        button: { label: "买", action: { kind: "buy_relic", slot } },
      });
    }
    return {
      title: `商店 · 删卡 ${s.removePrice} 金`,
      lines: [],
      rows,
      buttons: [
        { id: "remove", label: "删一张牌", action: { kind: "remove_card" } },
        { id: "leave", label: "离开", action: { kind: "leave" } },
      ],
    };
  }

  function describeChest(s) {
    return {
      title: "宝箱",
      lines: [],
      rows: [],
      buttons: [
        { id: "open", label: "开箱", action: { kind: "open_chest" } },
        { id: "leave", label: "离开", action: { kind: "leave" } },
      ],
    };
  }

  function describeReward(s) {
    const rows = [];
    for (const [slot, card] of (s.rewardCards || []).entries()) {
      rows.push({
        label: card.title || card.id,
        sub: card.chip,
        value: card.id,
        disabled: false,
        card: `reward:${slot}`,
        button: { label: "拿这张", action: { kind: "take_card", slot } },
      });
    }
    // `inv:§9.3`: the potion is its own offer -- taking the card and taking the potion are separate.
    if (s.rewardPotion) {
      rows.push({
        label: `药水 ${s.rewardPotion}`,
        sub: "",
        value: "",
        disabled: false,
        button: { label: "拿起", action: { kind: "take_potion" } },
      });
    }
    return {
      title: `战斗奖励 · 已得 ${s.rewardGold} 金 · 选一张牌`,
      lines: [],
      rows,
      buttons: [{ id: "skip", label: "跳过", action: { kind: "skip_reward" } }],
    };
  }

  function describeEvent(s) {
    const buttons = (s.choices || []).map((choice, slot) => {
      const suffix = effectText(choice.effect, choice.amount);
      return {
        id: `choice-${slot}`,
        label: choice.label,
        sub: suffix === "" ? "" : `（${suffix}）`,
        action: { kind: "event_choice", slot },
      };
    });
    return {
      title: `未知房间 · ${s.eventText}`,
      lines: [],
      rows: [],
      buttons,
    };
  }

  function describeBlessingCard(s) {
    const what = s.blessingNeeds === 2 ? "升级哪一张牌？" : "移除哪一张牌？";
    return {
      title: "塔底 · " + what,
      lines: [],
      rows: [],
      buttons: [{ id: "pick", label: "选一张牌", action: { kind: "blessing_card" } }],
    };
  }

  function describeIdle(s) {
    if (s.kind < 0) {
      return { title: "", lines: ["还没出发 · 点亮的节点可以走"], rows: [], buttons: [] };
    }
    return { title: "", lines: ["这个节点没有可做的事"], rows: [], buttons: [] };
  }

  /// The whole decision, in one place. `snapshot` is plain data (see `runSnapshot()` in
  /// `index.html`); this function is pure and is what `ui_test.mjs` exercises.
  function describe(s) {
    if (s.cleared) return describeCleared(s);
    if (s.runOver) return describeOver(s);
    switch (s.pending) {
      case 6:
        return describeBlessing(s);
      case 7:
        return describeBlessingCard(s);
      case 4:
        return describeReward(s);
      case 5:
        return describeEvent(s);
      case 3:
        return describeChest(s);
      case 2:
        return describeShop(s);
      case 1:
        return describeRest(s);
      case 0:
        if (s.kind === 1 || s.kind === 2 || s.kind === 7) return describeFight(s);
        if (s.kind >= 0 && s.actionCount === 0) {
          // No moves and nothing to settle: the act has run out of map (the last row, with no way
          // onward). Saying so beats an empty panel that looks like a bug.
          return {
            title: "",
            lines: ["第一幕到此为止（这一步之后没有可走的节点）"],
            rows: [],
            buttons: [{ id: "done", label: "就到这里", action: { kind: "end_act" } }],
          };
        }
        return describeIdle(s);
      default:
        return describeIdle(s);
    }
  }

  return { describe, effectText, KIND_NAMES, EFFECT_LABELS, statsLine, tone };
})();

if (typeof globalThis !== "undefined") globalThis.RD_PANELS = RD_PANELS;
