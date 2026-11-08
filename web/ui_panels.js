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
  /// Effect code -> Chinese label. The kernel's closed vocabulary (`docs/port-plan.md` §80, §143).
  const EFFECT_LABELS = [
    "",
    "回复",
    "金币",
    "受伤",
    "最大 HP",
    "什么也不做",
    "删一张牌",
    "升级一张牌",
    "转化一张牌",
    "获得一张诅咒",
    "获得遗物",
    "按上限百分比受伤",     // 11（§278）
    "按上限百分比减少最大 HP", // 12
    "花金币",               // 13（§280）
    "按上限百分比回复",     // 14
    "回满血",               // 15
  ];

  /// §280：11/12/14 的"数"是**千分比**（`250` = 25%，`125` = 12.5%）。
  /// 这是唯一需要小数的一位，所以单独一个格式化函数（而不是让每个调用点自己除）。
  function permilleText(tenths) {
    const whole = Math.floor(tenths / 10);
    const rest = tenths % 10;
    return rest === 0 ? `${whole}%` : `${whole}.${rest}%`;
  }

  /// Kind number -> what to call it. Order is `run-layer.md` §7.2.
  const KIND_NAMES = ["", "战斗", "精英", "篝火", "商人", "未知", "宝箱", "Boss"];

  /// The effect phrase for an offer/choice half, or `""` when it does nothing.
  function effectText(code, amount) {
    if (code === 5 || code < 0) return "";
    // §280：百分比三项的数是千分比，要写成 `25%` / `12.5%`（不是 `250`）。
    if (code === 11 || code === 12 || code === 14) {
      return `${EFFECT_LABELS[code] || "?"} ${permilleText(amount)}`;
    }
    // §143: codes 6..=10 are not "amount" effects -- the number belongs to the number effects
    // only, so appending it would print "升级一张牌 0".
    if (code >= 13) return EFFECT_LABELS[code] || "?";
    if (code >= 6) return EFFECT_LABELS[code] || "?";
    return `${EFFECT_LABELS[code] || "?"} ${amount}`;
  }

  /// `blessing` / `friendly` / `danger` -- the page only chooses a CSS class from this.
  function tone(snapshot) {
    if (snapshot.cleared) return "good";
    if (snapshot.runOver) return "danger";
    return "";
  }

  function statsLine(s) {
    // §303: `wing_boots` 的剩余次数只在还有次数时出现 —— 没有这件遗物时这一行与从前
    // **逐字相同**（既有页面判据比的是字符串，多一个字就会红）。
    const boots = s.wingBoots > 0 ? ` · 飞行 ${s.wingBoots}` : "";
    return (
      `floor ${s.floor} · hp ${s.hp}/${s.hpMax} · gold ${s.gold} · ` +
      `deck ${s.deckCount} · relics ${s.relicCount}${boots}`
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
    // §272：`?` 房掷出怪物时也是一场普通战斗（kind 仍是 5，靠 `unknownRoom === 2` 认出来）。
    const name =
      s.kind === 7
        ? `Boss · ${s.bossName}`
        : s.kind === 2
          ? "精英节点（3 × Sentry）"
          : s.kind === 5
            ? (s.eventFight > 0 ? "? 房 · 事件引来的伏击" : "? 房 · 普通战斗")
            : "战斗节点";
    return {
      title: name,
      lines: [],
      rows: [],
      buttons: [{ id: "fight", label: "开始战斗", action: { kind: "begin_fight" } }],
    };
  }

  function describeRest(s) {
    // §259: the campfire is **six** options now, and which ones exist is the kernel's answer
    // (`rd_run_campfire_options` -> a bit mask). The page must not decide ("if I hold Girya show
    // Lift"): that would be a second copy of the rule, and the two copies would drift the moment a
    // relic also closes an option (`Coffee Dripper`).
    const bits = Number.isFinite(s.campfire) ? s.campfire : 0;
    const buttons = [];
    if (bits & 1) buttons.push({ id: "rest", label: `休息（+${s.restHeal}）`, action: { kind: "rest" } });
    if (bits & 2) buttons.push({ id: "smith", label: "打铁（选一张升级）", action: { kind: "smith" } });
    if (bits & 8) buttons.push({ id: "lift", label: `举铁（力量 +1，已用 ${s.giryaLifts}/3）`, action: { kind: "lift" } });
    if (bits & 16) buttons.push({ id: "toke", label: "抽烟斗（删一张牌）", action: { kind: "toke" } });
    if (bits & 32) buttons.push({ id: "dig", label: "挖掘（拿一件随机遗物）", action: { kind: "dig" } });
    if (bits & 4) buttons.push({ id: "recall", label: "回想（拿红钥匙）", action: { kind: "recall" } });
    buttons.push({ id: "leave", label: "离开", action: { kind: "leave" } });
    const lines = [];
    // A greyed-out option is information: say *why* it is missing instead of leaving the player
    // wondering whether the page forgot it.
    if (!(bits & 1)) lines.push("休息被遗物关闭（Coffee Dripper / Mark of the Bloom）");
    if (!(bits & 2)) lines.push("打铁不可用（Fusion Hammer，或牌组里已经没有可升级的牌）");
    if (s.giryaLifts >= 3 && (s.relics || []).includes("girya")) lines.push("举铁已用满 3 次");
    return { title: `篝火 · 回复 ${s.restHeal}`, lines, rows: [], buttons };
  }

  function describeShop(s) {
    const rows = [];
    for (const [slot, card] of (s.shopCards || []).entries()) {
      rows.push({
        label: card.title || card.id,
        sub: card.chip,
        value: card.price < 0 ? "已售" : `${card.price} 金`,
        // §151: **unaffordable is disabled too**. Until the soak test clicked one, every shop showed
        // a live 买 button whose only possible outcome was `被拒 · NotEnoughGold`. The price stays on
        // screen, so the reason is visible without the button pretending it could work.
        disabled: card.price < 0 || (card.price >= 0 && card.price > s.gold),
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
        disabled: relic.price < 0 || (relic.price >= 0 && relic.price > s.gold),
        button: { label: "买", action: { kind: "buy_relic", slot } },
      });
    }
    return {
      title: `商店 · 删卡 ${s.removePrice} 金`,
      lines: [],
      rows,
      buttons: [
        {
          id: "remove",
          label: "删一张牌",
          // Same rule: a 75-gold removal with 23 gold is not a button, it is a price list.
          disabled: s.removePrice > s.gold,
          action: { kind: "remove_card" },
        },
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
    for (const card of s.rewardCards || []) {
      // §161.8: `card.slot` is the kernel's slot; the array position is a page artifact and stops
      // matching the moment a row is blanked by `take_card`.
      rows.push({
        label: card.title || card.id,
        sub: card.chip,
        value: card.id,
        disabled: false,
        card: `reward:${card.slot}`,
        button: { label: "拿这张", action: { kind: "take_card", slot: card.slot } },
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
    // §155: elites and bosses pay a relic (StS's elite reward is gold + cards + a relic). Its own
    // row, on the same "one offer, one button" rule the potion already follows.
    if (s.rewardRelic) {
      rows.push({
        label: `遗物 ${s.rewardRelic}`,
        sub: "",
        value: "",
        disabled: false,
        button: { label: "拿起", action: { kind: "take_relic" } },
      });
    }
    const buttons = [{ id: "skip", label: "跳过", action: { kind: "skip_reward" } }];
    // §293：`singing_bowl` —— "加牌时可以不拿牌、改拿 +2 上限"。只在**牌还在**的时候画：
    // 牌已经被拿走之后，这条动作会被内核拒（`EmptyOffer`），画出来就是死按钮。
    if (s.singingBowl && (s.rewardCards || []).length > 0) {
      buttons.unshift({
        id: "max_hp",
        label: "+2 上限（不拿牌）",
        action: { kind: "take_max_hp_instead" },
      });
    }
    return {
      title: `战斗奖励 · 已得 ${s.rewardGold} 金 · 选一张牌`,
      lines: [],
      rows,
      buttons,
    };
  }

  function describeEvent(s) {
    // §279：条件不成立的选项**不画**（wiki 的 `[Locked] Requires: …` 是另一套 UI，我们没有
    // 锁标，所以直接不给按钮）。★ 槽号必须用**条目自己的 `slot`**，不能用过滤后的下标 ——
    // 否则"第二段的第 2 个按钮"会打给内核第 1 个槽，而屏幕上一切正常。
    const buttons = (s.choices || []).filter((choice) => choice.available !== false)
      .map((choice) => {
      // §188：`effects` 是整张列表（遗物 + 诅咒就是两条）；没有就退回单条的旧字段。
      const list = Array.isArray(choice.effects) && choice.effects.length
        ? choice.effects
        : [{ effect: choice.effect, amount: choice.amount }];
      const suffix = list
        .map((entry) => effectText(entry.effect, entry.amount))
        .filter((text) => text !== "")
        .join("、");
      const slot = choice.slot;
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

  /// §274: a relic that owes a deck edit (`empty_cage` 2 removals, `astrolabe` 3 transforms).
  ///
  /// **不靠 `pending`**：遗物欠的这几步可以叠在奖励屏/宝箱屏上（打完 Boss 拿 Boss 遗物、还想接着
  /// 拿卡牌奖励那条路径）。所以判据是 `pickupPicks > 0`，而它在 `describe` **最前面** ——
  /// 于是它压过后面所有面板，选完自然回到原来那一屏。
  function describePickupCard(s) {
    const names = {
      1: "移除哪一张牌？",
      2: "升级哪一张牌？",
      3: "转化哪一张牌？",
      4: "转化并升级哪一张牌？",
    };
    const what = names[s.pickupChange] || "选一张牌";
    const left = s.pickupPicks > 1 ? `（还要选 ${s.pickupPicks} 张）` : "";
    return {
      title: "遗物 · " + what + left,
      lines: [],
      rows: [],
      buttons: [{ id: "pick", label: "选一张牌", action: { kind: "pickup_card" } }],
    };
  }

  /// §143: an event choice that edits the deck leaves a pick owed (`Pending::EventCard` = 8).
  ///
  /// Its own state rather than reusing the blessing panel: the two are finished by two different
  /// kernel calls, and this panel's title has to say **which** edit the event asked for.
  function describeEventCard(s) {
    const names = { 1: "移除哪一张牌？", 2: "升级哪一张牌？", 3: "转化哪一张牌？" };
    const what = names[s.eventNeeds] || "选一张牌";
    return {
      title: "未知房间 · " + what,
      lines: [],
      rows: [],
      buttons: [{ id: "pick", label: "选一张牌", action: { kind: "event_card" } }],
    };
  }

  /// §293: a relic that owes **cards to add** (`orrery` 5, `tiny_house` 1).
  ///
  /// 与 `describePickupCard` 同一个位置、同一条理由（独立于 `pending`、优先级最高、选完回到原屏）。
  /// ★ 每个候选的按钮带的是**内核的槽号**（`slot`），不是数组下标 —— §161.8 的教训。
  function describePickupAdd(s) {
    const left = s.pickupAdd > 1 ? `（还要选 ${s.pickupAdd} 张）` : "";
    const rows = (s.pickupOffer || []).map((card) => ({
      label: card.title || `#${card.slot}`,
      sub: "",
      value: "",
      disabled: false,
      button: { label: "加这张", action: { kind: "pickup_add_card", slot: card.slot } },
    }));
    const buttons = [{ id: "skip", label: "跳过", action: { kind: "pickup_add_skip" } }];
    // ⚠️ 只在**持有 `singing_bowl`** 时画这个按钮：`pickup_add_max_hp` 没有那件遗物会
    // `UnsupportedRelic`，画出来就是一个点了没反应的死按钮。
    if (s.singingBowl) {
      buttons.unshift({ id: "max_hp", label: "+2 上限", action: { kind: "pickup_add_max_hp" } });
    }
    return {
      title: "遗物 · 挑一张牌加入牌组 " + left,
      lines: [],
      rows,
      buttons,
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
    // §274：遗物欠着的牌组编辑**优先于一切面板** —— 它可能叠在奖励屏/宝箱屏上，
    // 而"还要选几张"是玩家此刻唯一能做的事。
    if (s.pickupPicks > 0) return describePickupCard(s);
    // §293：加牌的欠账压过一切面板（与上面那条同一个理由）。
    if (s.pickupAdd > 0) return describePickupAdd(s);
    if (s.cleared) return describeCleared(s);
    if (s.runOver) return describeOver(s);
    switch (s.pending) {
      case 6:
        return describeBlessing(s);
      case 7:
        return describeBlessingCard(s);
      case 8:
        return describeEventCard(s);
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
        // §272：`?` 房（5）掷出怪物（`unknownRoom === 2`）时是战斗。
        if (s.kind === 1 || s.kind === 2 || s.kind === 7) return describeFight(s);
        if (s.kind === 5 && s.unknownRoom === 2) return describeFight(s);
        // §286：事件把房间变成了一场战斗（`Dead Adventurer` 的伏击）。判据是内核记下的
        // **档位**，不是"kind 是 5 就该打" —— 事件、宝箱、商人都还是 kind 5。
        if (s.eventFight > 0) return describeFight(s);
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
