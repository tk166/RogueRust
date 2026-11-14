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
    // §332：无色货架与药水货架。价格规则与上面两排相同（买不起就不给按钮）。
    for (const [slot, card] of (s.shopColorless || []).entries()) {
      rows.push({
        label: card.title || card.id,
        sub: "无色",
        value: card.price < 0 ? "已售" : `${card.price} 金`,
        disabled: card.price < 0 || (card.price >= 0 && card.price > s.gold),
        card: `shop_colorless:${slot}`,
        button: { label: "买", action: { kind: "buy_colorless", slot } },
      });
    }
    // §380：药水这一排还要看**腰带放不放得下**（容量是内核的规则：3 / A11 减 1 / potion_belt 加 2）。
    // 旧版只看金币 ⇒ 腰带 3/3 时"买"是亮的，点下去被内核拒绝（`web-soak` 的 dead control）。
    const beltFull = s.potionSlots > 0 && s.potionsHeld >= s.potionSlots;
    for (const [slot, potion] of (s.shopPotions || []).entries()) {
      rows.push({
        label: potion.title || potion.id,
        sub: beltFull ? "药水 · 腰带满了" : "药水",
        value: potion.price < 0 ? "已售" : `${potion.price} 金`,
        disabled: beltFull || potion.price < 0 || (potion.price >= 0 && potion.price > s.gold),
        button: { label: "买", action: { kind: "buy_potion", slot } },
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
          // §343：这家店删过了也不是按钮（wiki: "Can only be used once per Shop"）。
          // ⚠️ 判据写成 `=== 0`（内核**明确**说用过了）而不是 `!== 1`：老夹具没有这个字段，
          // `!== 1` 会把它们的按钮也禁掉 —— 那是夹具的事，不是规则的事。
          disabled: s.removePrice > s.gold || s.removalAvailable === 0,
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

  /// §320: an event that offered a **list of new cards** (`Pending::EventOffer` = 9).
  ///
  /// `The Library` 的 `[Read]` 是 20 选 1、`Sensory Stone` 的每次 `[Recall]` 是 3 选 1；
  /// 两者在运行层是同一件事，所以面板也只有这一份 —— 标题只说"从候选里拿一张"，
  /// 具体几张由内核给的 `rows` 决定（页面不写死 3，也不写死 20）。
  function describeEventOffer(s) {
    const rows = (s.eventOffer || []).map((card) => ({
      label: card.title || card.id || `#${card.slot}`,
      sub: "",
      value: "",
      disabled: false,
      button: { label: "拿这张", action: { kind: "event_offer_take", slot: card.slot } },
    }));
    return {
      title: "未知房间 · 从 " + rows.length + " 张里选一张加入牌组",
      lines: [],
      rows,
      buttons: [],
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
  // ---------------------------------------------------------------------------------------------
  // §347: the scene table, as code.
  //
  // `docs/ui-state-model.md` §1 是 18 行散文，而"先成立的赢"这个顺序以前**只有文档**在说。
  // 于是：表里排错一行没人能发现、`describe()` 里那串 if/switch 是第二份同样的顺序、
  // 3D 重写要重新推导一遍。现在顺序只有一份 —— **数组即优先级**，`classifyScene` 取第一条命中的。
  //
  // 每个谓词只用**内核事实**（`rd_run_*` / `rd_env_*` 经快照转述），不用页面自己的历史
  // （§341 的 `in_fight`、§344 的 `run_end` 就是为这件事加进来的）。
  // ---------------------------------------------------------------------------------------------

  /// 战斗节点（或"会打起来"的房间）。三个来源：节点种类、`?` 房掷出怪物、事件引来的伏击。
  function preFight(s) {
    if (s.kind === 1 || s.kind === 2 || s.kind === 7) return true;
    // §272：`?` 房（kind 5）掷出怪物（`unknownRoom === 2`）时是一场普通战斗。
    if (s.kind === 5 && s.unknownRoom === 2) return true;
    // §286：事件把房间变成了一场战斗（`Dead Adventurer` 的伏击）。判据是内核记下的**档位**，
    // 不是"kind 是 5 就该打" —— 事件、宝箱、商人都还是 kind 5。
    return s.eventFight > 0;
  }

  /// 地图上还有下一步可走吗？（`actionCount` 就是 `reachable().len()`。）
  function mapExhausted(s) {
    return s.kind >= 0 && s.actionCount === 0;
  }

  /// 场景表：**数组顺序就是优先级**（与 `ui-state-model.md` §1 的表格逐行对应）。
  ///
  /// `overlay: true` 的两条是**叠在**别的屏上的（§3.13：遗物欠账可以压着奖励屏），所以它们
  /// 与底下那一屏**同时命中是正确的** —— 判据显式允许这一种共命中。
  /// 场景表：**数组顺序就是优先级**（与 `ui-state-model.md` §1 的表格逐行对应）。
  ///
  /// 每条只写**自己的**条件；"前面没人命中"由下面的 `SCENES` 统一加上（构造即互斥）。
  const RAW = [
    // 1 未开局：没有局。`noRun` 来自 **`rd_run_exists()`**（§348）—— **不是** seed 哨兵：
    // `i32::MIN` 是一个合法 seed，拿它当"无值"会让那一局被判成未开局。
    { id: "SC-00", overlay: false, test: (s) => !!s.noRun },
    // 2 战斗中：内核说"有一场在打"（§341 的 `rd_run_in_fight`）。它必须排在"预备战斗"之前，
    //   否则站在战斗节点上时两个屏都会命中，而顺序会替你选一个。
    { id: "SC-03b", overlay: false, test: (s) => !!s.inFight },
    // 3/4 遗物欠账（覆盖层）：它可能叠在奖励屏/宝箱屏上，而"还要选几张"是此刻唯一能做的事。
    { id: "SC-11a", overlay: true, test: (s) => s.pickupPicks > 0 },
    { id: "SC-11b", overlay: true, test: (s) => s.pickupAdd > 0 },
    // 5/6 终局。局终优先于"幕通关"（两者在页面侧本来就互斥，但顺序仍然写死）。
    { id: "SC-12b", overlay: false, test: (s) => !!s.runOver },
    { id: "SC-12a", overlay: false, test: (s) => !!s.cleared },
    // 7..15 具体的待决问句（`Pending` 的判别值）。
    { id: "SC-01", overlay: false, test: (s) => s.pending === 6 },
    { id: "SC-01b", overlay: false, test: (s) => s.pending === 7 },
    { id: "SC-09", overlay: false, test: (s) => s.pending === 8 },
    { id: "SC-10", overlay: false, test: (s) => s.pending === 9 },
    { id: "SC-04", overlay: false, test: (s) => s.pending === 4 },
    { id: "SC-08", overlay: false, test: (s) => s.pending === 5 },
    { id: "SC-07", overlay: false, test: (s) => s.pending === 3 },
    { id: "SC-05", overlay: false, test: (s) => s.pending === 2 },
    { id: "SC-06", overlay: false, test: (s) => s.pending === 1 },
    // 16 预备战斗：站在战斗节点上、**还没开打**。`!inFight` 是必须的 —— 少了它，
    //    "战斗中 + 站在战斗节点上"会同时命中 SC-03b 与 SC-03，而顺序会把这件事藏起来。
    { id: "SC-03", overlay: false, test: (s) => s.pending === 0 && !s.inFight && preFight(s) },
    // 17 幕尽头：没有下一步可走（M1 的地图走到最后一排）。
    { id: "SC-02b", overlay: false, test: (s) => s.pending === 0 && !s.inFight && mapExhausted(s) },
    // 18 地图（兜底）：**只在"无待决"时**才是兜底。
    //
    // §348（第十轮 Review P2-2）：这里原来是 `() => true`，于是 `SC-??` **不可达** ——
    // 将来内核新增一个 `Pending`，页面会静默把它画成普通地图。现在表外的 `pending`
    // 会落到 `SC-??`，由 `describe` 给一份**显式**的"未知状态"面板。
    { id: "SC-02", overlay: false, test: (s) => s.pending === 0 },
  ];

  // 包装层：**构造即互斥**。
  //
  // 基础场景额外要求"**前面没有任何基础场景命中**"（覆盖层不参与这个判断，它们按定义叠着）。
  // 这样 `classifyScene` 的"第一条命中"与"唯一命中"是同一件事 —— 而手写否定式做不到：
  // 它漏过两次（`pending === 0` 是超集；补上之后又漏了 `runOver`），两次的表现都是
  // "两个场景同时命中"，而顺序把错误藏起来。
  const SCENES = RAW.map((entry, index) => {
    if (entry.overlay) return entry;
    return {
      ...entry,
      test: (s) =>
        !RAW.slice(0, index).some((earlier) => !earlier.overlay && earlier.test(s)) &&
        entry.test(s),
    };
  });

  /// 这个快照属于哪个场景。**取第一条命中的** —— 顺序就是 `SCENES` 的顺序。
  function classifyScene(s) {
    for (const scene of SCENES) {
      if (scene.test(s)) return scene.id;
    }
    // 走到这里说明 `pending` 是一个表外的值（`-1` 没有局、或以后新增的待决态）。
    return "SC-??";
  }

  /// **复合**状态：基础场景与覆盖层**分开**（§349，第十一轮 Review P2-A）。
  ///
  /// `classifyScene` 返回的是"第一个命中的 id"，所以"奖励屏 + 遗物选牌欠账"只报 `SC-11a`，
  /// 底下那一屏（`SC-04`）就丢了。DOM 面板"用覆盖层暂时替换正文"是合理权衡，但 3D 需要知道
  /// **两层都在**（覆盖层画在底屏之上）。
  ///
  /// | 字段 | 含义 |
  /// |---|---|
  /// | `base` | 第一个命中的**非覆盖层**场景；一条都没命中 ⇒ `"SC-??"` |
  /// | `overlays` | 命中的覆盖层（按优先级），可以为空、也可以是两个 |
  /// | `unknownPending` | 只在 `base === "SC-??"` 时有值：那个表外的 `pending` |
  function resolveScene(s) {
    const overlays = RAW.filter((entry) => entry.overlay && entry.test(s)).map((entry) => entry.id);
    const base = SCENES.find((entry) => !entry.overlay && entry.test(s));
    return {
      base: base ? base.id : "SC-??",
      overlays,
      unknownPending: base ? null : s.pending,
    };
  }

  /// **所有**命中的场景 id（按优先级）。判据用它验"唯一命中"：多重命中会被顺序藏起来，
  /// 而那正是"表里排错一行"的形状。
  function scenesMatching(s) {
    return SCENES.filter((scene) => scene.test(s)).map((scene) => scene.id);
  }

  /// 这个场景是覆盖层吗（可以叠在别的屏上）？
  function isOverlay(sceneId) {
    const found = SCENES.find((scene) => scene.id === sceneId);
    return !!(found && found.overlay);
  }

  /// **唯一**决策点：场景 → 那一屏怎么画。`describe` 不再自己判顺序。
  function describe(s) {
    switch (classifyScene(s)) {
      case "SC-11a":
        return describePickupCard(s);
      case "SC-11b":
        return describePickupAdd(s);
      case "SC-12a":
        return describeCleared(s);
      case "SC-12b":
        return describeOver(s);
      case "SC-01":
        return describeBlessing(s);
      case "SC-01b":
        return describeBlessingCard(s);
      case "SC-09":
        return describeEventCard(s);
      // §320：候选列表（事件摊开的新牌）。与 `EventCard` 分开：那一个收**牌组下标**，
      // 这一个收**候选槽号**，两个调用不同。
      case "SC-10":
        return describeEventOffer(s);
      case "SC-04":
        return describeReward(s);
      case "SC-08":
        return describeEvent(s);
      case "SC-07":
        return describeChest(s);
      case "SC-05":
        return describeShop(s);
      case "SC-06":
        return describeRest(s);
      case "SC-03":
        return describeFight(s);
      case "SC-02b":
        // No moves and nothing to settle: the act has run out of map (the last row, with no way
        // onward). Saying so beats an empty panel that looks like a bug.
        return {
          title: "",
          lines: ["第一幕到此为止（这一步之后没有可走的节点）"],
          rows: [],
          buttons: [{ id: "done", label: "就到这里", action: { kind: "end_act" } }],
        };
      // SC-??：**表外状态**（内核给了一个场景表里没有的 `pending`）。
      //
      // §348：它必须**显性**说出来，而不是画成地图或"这个节点没有可做的事" ——
      // 静默降级正是"新增一个 Pending，UI 悄悄画错屏"的形状。
      case "SC-??":
        return {
          title: "未知状态",
          lines: [`内核给的待决值 ${s.pending} 不在场景表里 · 这一屏不知道怎么画`],
          rows: [],
          buttons: [],
        };
      // SC-00 / SC-02 / SC-03b 落在 `describeIdle`：它们不是"节点面板"那一屏
      // （战斗由 `render()` 画、地图由 `renderMap()` 画），节点面板只是兜底。
      default:
        return describeIdle(s);
    }
  }

  return {
    describe, effectText, KIND_NAMES, EFFECT_LABELS, statsLine, tone,
    // §347：场景表本身（数组即优先级）+ 分类器 + 判据用的"全部命中"
    SCENES, classifyScene, resolveScene, scenesMatching, isOverlay, preFight, mapExhausted,
  };
})();

if (typeof globalThis !== "undefined") globalThis.RD_PANELS = RD_PANELS;
