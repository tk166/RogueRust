// `RunStore`：运行层的**唯一写入者**（P3 的场景层核心）。
//
// ## 三条纪律
//
// 1. **组件不碰 `instance.exports`**：场景只读 `getState()` 与 `subscribe()`。
// 2. **场景由内核事实派生**：`scene` 字段是 `resolveScene(事实)` 的结果，UI **没有** mode 变量。
//    "刷新一下回到地图"这种 bug 在结构上不可能出现 —— 因为屏幕是算出来的。
// 3. **每次改动都**对账**（`reconcile()`）：HP / 金币 / 牌组数 / 战斗会话存在性必须与内核一致。
//    不一致不是"显示小错"，是 ABI 违约 ⇒ 界面冻结并显示诊断（与 P2 的 `isContractViolation` 同一条）。
//
// ## 为什么运行层动作要自己找"位置"
//
// `rd_run_step` 收的是**可达表里的位置**，而地图上点的是**全局节点下标**（`env-abi.md` §11.2/§11.4）。
// 直接把节点下标丢进 `rd_run_step` 会在"第 2 行第 1 个可达"时走错格子 —— 所以这里先按
// `runActions()` 找 `target === 全局下标` 的那一条。

import type { WasmHost } from "../wasm/host";
import { GameStore, type DispatchResult } from "../wasm/store";
import type { CombatAction } from "../wasm/snapshot";
import {
  BOSS_SENTINEL,
  buildMap,
  decodeRun,
  opensFight,
  type MapModel,
  type RunSnapshot,
} from "./observe.js";
import { resolveScene, type SceneInput, type SceneResolution } from "./scene.js";

export interface LogEntry {
  readonly seq: number;
  readonly text: string;
  readonly kind: "info" | "good" | "warn" | "bad";
}

export interface RunState {
  readonly run: RunSnapshot | null;
  readonly map: MapModel | null;
  readonly scene: SceneResolution;
  /**
   * Boss 哨兵这一步能不能进。
   *
   * 它**不在** `map.nodes` 里（第 16 层在地图之外），所以地图屏要单独问这一句；
   * 少了它，第 15 层之后就没有可点的格子（软锁）。
   */
  readonly bossReachable: boolean;
  /** 当前相位（`rd_run_pending`）：0 = 没有待决屏。诊断与"未实现屏"都用它。 */
  readonly pending: number;
  readonly seed: number;
  readonly ascension: number;
  /** 局终原因（`RunEnd` 判别值）；`0` = 还在进行。 */
  readonly overWhy: number;
  /** 当前遭遇 id（战斗前/战斗中显示）。 */
  readonly encounter: string;
  /** 祝福候选（`SC-01`）。 */
  readonly blessings: readonly {
    slot: number;
    id: string;
    gain: number;
    gainAmount: number;
    cost: number;
    costAmount: number;
  }[];
  /** 战斗快照（`null` = 没有战斗会话）。 */
  readonly combat: ReturnType<GameStore["getSnapshot"]>;
  /** 奖励屏内容。 */
  readonly reward: {
    readonly gold: number;
    readonly cards: readonly { slot: number; id: string; title: string }[];
    readonly potion: string;
    readonly relic: string;
  };
  /** 商店（`pending == 2`）。 */
  readonly shop: {
    readonly cards: readonly { slot: number; id: string; price: number }[];
    readonly relics: readonly { slot: number; id: string; price: number }[];
    readonly potions: readonly { slot: number; id: string; price: number }[];
    readonly colorless: readonly { slot: number; id: string; price: number }[];
    readonly removePrice: number;
    readonly removalAvailable: number;
  };
  /** 篝火（`pending == 1`）。`options` 是**位掩码**，解码在 `models.ts`。 */
  readonly rest: {
    readonly options: number;
    readonly heal: number;
    readonly giryaLifts: number;
  };
  /**
   * 刚刚拿到的东西（宝箱/挖宝）。
   *
   * ⚠️ 为什么需要它：`rd_run_open_chest()` 的语义是**打开即结束**（相位直接归 0），
   * 所以"已打开的宝箱"不是一个可停留的屏。第一版按"打开 → 看战利品 → 离开"设计，
   * 结果点完打开相位就没了，界面还在等一个永远不会来的"离开"按钮。
   * 现在把增量记在这里，由外壳画一条横幅（可关），比编一个假屏诚实。
   */
  readonly lastLoot: { readonly gold: number; readonly relic: string; readonly source: string } | null;
  /** 宝箱（`pending == 3`）：打开前后的增量。 */
  readonly chest: {
    readonly opened: boolean;
    readonly goldGained: number;
    readonly relicGained: string;
  };
  /** 事件（`pending == 5` / `9`）。 */
  readonly event: {
    readonly id: string;
    readonly text: string;
    readonly needs: number;
    readonly options: readonly {
      slot: number;
      label: string;
      available: boolean;
      effects: readonly { kind: number; amount: number }[];
    }[];
    readonly offers: readonly { slot: number; id: string; title: string }[];
  };
  /** 遗物欠账（`SC-11a`/`SC-11b`，**不走 pending**）。 */
  readonly pickup: {
    readonly change: number;
    readonly picks: number;
    readonly add: number;
    readonly offers: readonly { slot: number; title: string }[];
  };
  /** 药水腰带（带 `effect`/`needsFight`，界面据此决定能不能用、要不要目标）。 */
  readonly potions: readonly { slot: number; id: string; effect: number; needsFight: number }[];
  /** 牌组 / 遗物（顶栏与牌组弹窗）。 */
  readonly deck: readonly string[];
  /** 牌组的显示名（与 `deck` 同序，供牌组选择器用）。 */
  readonly deckTitles: readonly string[];
  readonly relics: readonly string[];
  /** 对账失败项（空 = 一致）。非空时界面必须**响亮**显示。 */
  readonly violations: readonly string[];
  readonly log: readonly LogEntry[];
}

type Listener = () => void;

const EMPTY_REWARD = { gold: 0, cards: [], potion: "", relic: "" } as const;

export class RunStore {
  private readonly host: WasmHost;
  private combatStore: GameStore | null = null;
  private state: RunState;
  private readonly listeners = new Set<Listener>();
  private seq = 0;
  /**
   * 宝箱的"打开前"基线（金币 + 遗物数）。
   *
   * 内核没有"箱子里有什么"的查询，只有"打开之后局里多了什么"。所以进宝箱屏时记一次基线，
   * 打开后拿差值显示 —— 这比编一个"里面有 X"诚实。
   */
  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;
  /** 见 `RunState.lastLoot`。 */
  private lastLoot: RunState["lastLoot"] = null;
  private chestOpened = false;

  constructor(host: WasmHost) {
    this.host = host;
    this.state = {
      run: null,
      map: null,
      scene: { base: "SC-00", overlays: [], unknownPending: null },
      bossReachable: false,
      pending: 0,
      seed: 0,
      ascension: 0,
      overWhy: 0,
      encounter: "",
      blessings: [],
      combat: null,
      reward: EMPTY_REWARD,
      shop: { cards: [], relics: [], potions: [], colorless: [], removePrice: 0, removalAvailable: -1 },
      rest: { options: 0, heal: 0, giryaLifts: 0 },
      chest: { opened: false, goldGained: 0, relicGained: "" },
      lastLoot: null,
      event: { id: "", text: "", needs: 0, options: [], offers: [] },
      pickup: { change: 0, picks: 0, add: 0, offers: [] },
      potions: [],
      deck: [],
      deckTitles: [],
      relics: [],
      violations: [],
      log: [],
    };
    this.refresh();
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getState = (): RunState => this.state;

  /** 战斗 store（P2 的那一套原样复用：手势、动作表版本号、拒绝证明都在里面）。 */
  get combat(): GameStore | null {
    return this.combatStore;
  }

  /**
   * 战斗屏要的那个宿主（与运行层**同一个** wasm 实例）。
   *
   * 单独一个 getter 而不是把 `host` 变 public：组件不该顺手拿宿主去调别的导出，
   * 它只需要把它交给 `CombatScreen`（那一层再交给 `GameStore`）。
   */
  get hostForCombat(): WasmHost {
    return this.host;
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  /** 记一行日志（公开：地图上点了一个到不了的节点，也值得留痕）。 */
  note(text: string, kind: LogEntry["kind"] = "info"): void {
    this.seq += 1;
    this.state = {
      ...this.state,
      log: [...this.state.log.slice(-49), { seq: this.seq, text, kind }],
    };
  }

  /** 读一次全部事实并重算场景 + 对账。**所有**动作的结尾都调它。 */
  refresh(): RunState {
    const raw = this.host.run();
    const rawExtra = this.host.runRaw();
    const run = raw.exists ? decodeRun(this.host.runObservation()) : null;

    const mapLen = run ? this.host.mapLen() : 0;
    const map =
      run && mapLen > 0
        ? buildMap(mapLen, this.host.mapRows(), (index, field) => this.host.mapNode(index, field))
        : null;

    // 战斗会话：**存在性**来自 store（它才是"有没有 148 格向量"的判据）。
    const hasCombatSession = this.host.hasCombatSession();
    if (hasCombatSession && !this.combatStore) {
      this.combatStore = new GameStore(this.host);
      // ⚠️ **必须订阅**：战斗里的动作是 `CombatScreen` 直接调 `GameStore.dispatch` 发出去的，
      // 不经过这里。第一版没有这条订阅，于是出牌之后顶栏的能量/HP、对账用的 `state.combat`
      // 全都停在"战斗开始前"那一份 —— 闸门 34 实测：拖动提交成功、beat 也播了
      // （"打出 打击 · 敌人 0 −6 血"），但 `__run.hand()` 里能量还是 3、敌人还是 28 血。
      this.combatStore.subscribe(() => this.refresh());
    }
    if (!hasCombatSession && this.combatStore) this.combatStore = null;
    const combat = this.combatStore?.getSnapshot() ?? null;

    const actions = raw.exists ? this.host.runActions() : [];
    const input: SceneInput = {
      runExists: raw.exists,
      inFight: raw.inFight,
      hasCombatSession,
      pending: rawExtra.pending,
      over: rawExtra.over,
      bossBeaten: this.host.bossBeaten(),
      nodeKind: rawExtra.nodeKind,
      nodeResolved: rawExtra.nodeResolved === 1,
      unknownRoom: (run?.unknownRoom ?? 0) as SceneInput["unknownRoom"],
      eventFight: rawExtra.eventFight,
      actionCount: actions.length,
      pickupPicks: this.host.pickupPicks(),
      pickupAdd: this.host.pickupAdd(),
    };
    const scene = resolveScene(input);

    const pending = rawExtra.pending;
    this.state = {
      ...this.state,
      run,
      map,
      scene,
      bossReachable: actions.some((action) => action.target === BOSS_SENTINEL),
      pending,
      seed: raw.seed,
      ascension: raw.ascension,
      overWhy: this.host.overWhy(),
      encounter: raw.exists ? this.host.encounterId() : "",
      blessings: pending === 6 ? this.host.startOffers() : [],
      combat,
      reward:
        pending === 4
          ? {
              gold: this.host.rewardGold(),
              cards: this.host.rewardCards(),
              potion: this.host.rewardPotionId(),
              relic: this.host.rewardRelicId(),
            }
          : EMPTY_REWARD,
      shop:
        pending === 2
          ? {
              cards: this.host.shopCards(),
              relics: this.host.shopRelics(),
              potions: this.host.shopPotions(),
              colorless: this.host.shopColorless(),
              removePrice: this.host.removePrice(),
              removalAvailable: this.host.removalAvailable(),
            }
          : { cards: [], relics: [], potions: [], colorless: [], removePrice: 0, removalAvailable: -1 },
      rest:
        pending === 1
          ? {
              options: this.host.campfireOptions(),
              heal: this.host.restHeal(),
              giryaLifts: this.host.giryaLifts(),
            }
          : { options: 0, heal: 0, giryaLifts: 0 },
      chest: this.readChest(pending, raw.exists),
      // ⚠️ 用**字段**而不是 `this.state.lastLoot`：动作里刚设的字段还没进 state，
      // 读旧 state 会把它当场抹掉（第一版就是这样，宝箱横幅永远不出现）。
      lastLoot: this.lastLoot,
      event:
        pending === 5 || pending === 9
          ? {
              id: this.host.eventId(),
              text: this.host.eventText(),
              needs: this.host.eventNeeds(),
              options: pending === 5 ? this.host.eventOptions() : [],
              offers: pending === 9 ? this.host.eventOffers() : [],
            }
          : { id: "", text: "", needs: 0, options: [], offers: [] },
      pickup: {
        change: this.host.pickupChange(),
        picks: this.host.pickupPicks(),
        add: this.host.pickupAdd(),
        offers: this.host.pickupAdd() > 0 ? this.host.pickupOffers() : [],
      },
      potions: raw.exists
        ? Array.from({ length: this.host.potionCount() }, (_, slot) => ({
            slot,
            id: this.host.potionId(slot),
            effect: this.host.potionEffect(slot),
            needsFight: this.host.potionNeedsFight(slot),
          }))
        : [],
      deck: raw.exists ? this.host.deckIds() : [],
      deckTitles: raw.exists ? this.host.deckTitles() : [],
      relics: raw.exists ? this.host.relicIds() : [],
      violations: this.reconcile(input, run, combat, scene),
    };
    this.emit();
    return this.state;
  }

  /** 宝箱屏：进屏记基线，打开后拿差值。离开（相位不再是 3）就把状态清掉。 */
  private readChest(pending: number, exists: boolean): RunState["chest"] {
    if (!exists || pending !== 3) {
      this.chestBaseline = null;
      this.chestOpened = false;
      return { opened: false, goldGained: 0, relicGained: "" };
    }
    const run = decodeRun(this.host.runObservation());
    const relics = this.host.relicIds();
    if (this.chestBaseline === null) {
      this.chestBaseline = { gold: run.gold, relicCount: run.relicCount, relics };
    }
    const base = this.chestBaseline;
    const fresh = relics.filter((id) => !base.relics.includes(id));
    return {
      opened: this.chestOpened,
      goldGained: Math.max(0, run.gold - base.gold),
      relicGained: fresh[0] ?? "",
    };
  }

  /**
   * 对账（plan P3 的退出条件："所有 Snapshot 对账通过"）。
   *
   * 只比**能独立读两次**的东西 —— 同源比较没有意义：
   *   * 战斗内 HP 必须同时等于运行层 HP（两套导出，一个真相）；
   *   * 牌组数（观察向量里的 `deck_size`）必须等于 `rd_run_deck_count()` 的实际条数；
   *   * 遗物/药水数同理；
   *   * 场景说"在战斗"就必须真的有战斗会话，反之亦然。
   */
  private reconcile(
    input: SceneInput,
    run: RunSnapshot | null,
    combat: ReturnType<GameStore["getSnapshot"]>,
    scene: SceneResolution
  ): string[] {
    const bad: string[] = [];
    if (!run) {
      if (input.inFight) bad.push("没有局，但内核说在战斗中");
      return bad;
    }
    if (combat) {
      // ⚠️ **战斗内**运行层的 HP 是**故意**不跟的：战斗结算（`end_of_combat`）才写回，
      // 所以战斗中拿两边比会把每一场战斗都判成违约（第一版就是这么红的：
      // "战斗 HP 43 ≠ 运行层 HP 66"）。战斗中只比上限（它不会因为受伤而变）。
      // 战斗后的"写回正确"由闸门 34 用"最后一帧战斗 HP == 战后运行层 HP"钉住。
      if (input.inFight) {
        if (combat.hero.hpMax !== run.healthMax) {
          bad.push(`战斗上限 ${combat.hero.hpMax} ≠ 运行层上限 ${run.healthMax}`);
        }
      } else if (combat.hero.hp !== run.health) {
        bad.push(`战斗 HP ${combat.hero.hp} ≠ 运行层 HP ${run.health}`);
      }
    }
    const deck = this.host.deckIds();
    if (run.deckSize !== deck.length) {
      bad.push(`观察向量说牌组 ${run.deckSize} 张，实际 ${deck.length} 张`);
    }
    const relics = this.host.relicIds();
    if (run.relicCount !== relics.length) {
      bad.push(`观察向量说遗物 ${run.relicCount} 个，实际 ${relics.length} 个`);
    }
    const potions = this.host.potionCount();
    if (run.potionCount !== potions) {
      bad.push(`观察向量说药水 ${run.potionCount} 瓶，实际 ${potions} 瓶`);
    }
    if (scene.base === "SC-03b" && !combat) bad.push("场景是战斗中，但没有战斗会话");
    if (scene.base !== "SC-03b" && combat) bad.push(`场景是 ${scene.base}，却还留着战斗会话`);
    if (scene.base === "SC-03" && !opensFight(input.nodeKind, input.unknownRoom) && input.eventFight === 0) {
      bad.push(`场景是战斗前，但这一格（kind ${input.nodeKind}）不开战斗`);
    }
    if (scene.unknownPending !== null) {
      bad.push(`内核给了未知相位 ${scene.unknownPending}（UI 的 PENDING_SCENE 表没跟上）`);
    }
    return bad;
  }

  // ── 动作 ──────────────────────────────────────────────────────────────────
  startRun(seed: number, ascension: number): void {
    this.host.startRun(seed, ascension);
    this.note(`开局：seed ${seed} · 进阶 ${ascension}`, "good");
    this.refresh();
  }

  chooseBlessing(slot: number): void {
    this.host.chooseStart(slot);
    this.note(`祝福：选了第 ${slot + 1} 项`, "good");
    this.refresh();
  }

  /**
   * 走到某个节点。
   *
   * ⚠️ 点的是**全局下标**，`rd_run_step` 收的是**可达表位置** —— 必须在这里翻译。
   * 不可达就**拒绝**（并且不改状态），而不是"尽力而为"。
   */
  enterNode(globalIndex: number): { ok: boolean; why?: string } {
    const action = this.host.runActions().find((candidate) => candidate.target === globalIndex);
    if (!action) {
      const why = `节点 ${globalIndex} 这一步不可达`;
      this.note(why, "warn");
      this.refresh();
      return { ok: false, why };
    }
    const code = this.host.runStep(action.index);
    if (code !== 0) {
      const why = `进入节点被拒绝（code ${code}）`;
      this.note(why, "warn");
      this.refresh();
      return { ok: false, why };
    }
    this.note(`走到第 ${this.host.runObservation()[0]} 层（节点 ${globalIndex}）`, "good");
    // 走进去之后**立刻结算这一格**。
    //
    // 为什么必须在这里做：篝火/商店/宝箱/事件节点的"进入"只移动游标，相位还是 0，
    // 场景会判成地图（SC-02）—— 玩家点了格子却还站在地图上，看起来就是"点了没反应"。
    // `begin_node` 才是让那一格开口说话的那一步（`run-layer.md` §4.7.1 的走/结算分离）。
    // 战斗节点调它也是对的：它只回一个 `Combat`，相位仍是 0，于是场景进 SC-03。
    const after = this.host.runRaw();
    if (after.pending === 0 && after.nodeResolved === 0) {
      const code = this.host.beginNode();
      if (code !== 0) this.note(`这一格结算失败（code ${code}）`, "bad");
    }
    this.refresh();
    return { ok: true };
  }

  /**
   * 结算脚下这个节点（篝火/宝箱/商店/事件会进各自的待决屏；战斗节点什么也不做）。
   *
   * ⚠️ `rd_run_begin_node()` 返回 **`0` = 已结算 / `-2` = 拒绝**，**不是**节点 kind。
   * 第一版把它当 kind 打日志，于是每一格都写成"进入节点：未分配"。
   */
  beginNode(): number {
    const code = this.host.beginNode();
    this.note(code === 0 ? "这一格已结算" : `这一格结算被拒绝（code ${code}）`, code === 0 ? "info" : "bad");
    this.refresh();
    return code;
  }

  /** 开打。**必须**由玩家显式触发（plan：战斗开始由权威 API 决定，不靠 UI mode）。 */
  fightBegin(): number {
    const code = this.host.fightBegin();
    if (code !== 0) this.note(`开战被拒绝（code ${code}）`, "bad");
    else this.note(`开战：${this.host.encounterId() || "遭遇"}`, "good");
    this.refresh();
    return code;
  }

  /**
   * 战斗结束 → 让运行层生成奖励屏（**这一步才会**有 `pending 4`）。
   *
   * ⚠️ `rd_run_fight_end()` 返回的是**战斗结果**（`1` 胜利 / `2` 战败 …），**不是** `0 = 成功`。
   * 第一版拿 `code === 0` 判成功，于是每一场胜利都被记成"战斗结算失败（code 1）"。
   */
  fightEnd(): number {
    const code = this.host.fightEnd();
    const ok = code >= 1;
    this.note(
      ok ? `战斗结束：${code === 1 ? "胜利" : code === 2 ? "战败" : `结果 ${code}`}` : `战斗结算失败（code ${code}）`,
      ok ? "good" : "bad"
    );
    this.refresh();
    return code;
  }

  /** 战斗动作：委托给 P2 的 `GameStore`（手势/版本号/拒绝证明都在那边）。 */
  dispatchCombat(action: CombatAction): DispatchResult {
    if (!this.combatStore) throw new Error("没有战斗会话");
    const outcome = this.combatStore.dispatch(action);
    this.refresh();
    return outcome;
  }

  takeRewardCard(slot: number): number {
    const code = this.host.takeCard(slot);
    if (code === 0) {
      const card = this.state.reward.cards.find((candidate) => candidate.slot === slot);
      this.note(`拿了 ${card?.title ?? card?.id ?? `第 ${slot + 1} 张`}`, "good");
    } else {
      this.note(`拿牌被拒绝（code ${code}）`, "warn");
    }
    this.refresh();
    return code;
  }

  skipReward(): number {
    const code = this.host.skipReward();
    if (code === 0) this.note("跳过奖励", "info");
    this.refresh();
    return code;
  }

  takeRewardPotion(): number {
    const code = this.host.takePotion();
    this.note(code === 0 ? "拿了药水" : `拿药水被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  takeRewardRelic(): number {
    const code = this.host.takeRelic();
    this.note(code === 0 ? "拿了遗物" : `拿遗物被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  /**
   * **用内核的默认动作通过当前待决屏**（P4 之前的诚实做法）。
   *
   * 商店/篝火/宝箱/事件/选牌都还没有真正的界面。与其画一个"点了没反应"的按钮，
   * 不如明说"这一屏还没做"，并给一个**确实会推进**的按钮。
   */
  settleDefault(): boolean {
    const pending = this.host.runRaw().pending;
    const ok = this.host.settlePendingRun();
    this.note(ok ? `用默认动作通过了相位 ${pending}` : `相位 ${pending} 没能通过`, ok ? "warn" : "bad");
    this.refresh();
    return ok;
  }

  // ── P4：商店 ────────────────────────────────────────────────────────────
  /**
   * 买一件东西。`kind` 与货架一一对应（`card` / `relic` / `potion` / `colorless`）。
   *
   * 返回内核的返回码：`0` 成功、`-1` 没有这个槽、`-2` 拒绝（金币不够/腰带满/相位不对）。
   * ⚠️ 失败时**不猜原因**，把码交给界面 —— 界面只显示"买不了（code N）"，
   * 而不是编一句可能是错的话。
   */
  buy(kind: "card" | "relic" | "potion" | "colorless", slot: number): number {
    const code =
      kind === "card"
        ? this.host.buyCard(slot)
        : kind === "relic"
          ? this.host.buyRelic(slot)
          : kind === "potion"
            ? this.host.buyPotion(slot)
            : this.host.buyColorless(slot);
    const names = { card: "卡牌", relic: "遗物", potion: "药水", colorless: "无色牌" } as const;
    this.note(code === 0 ? `买了${names[kind]}（槽 ${slot}）` : `买${names[kind]}失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  /** 付钱删一张牌（`index` 是**牌组下标**）。返回花掉的钱，`<0` 表示失败。 */
  removeFromDeck(index: number): number {
    const paid = this.host.removeCard(index);
    this.note(paid >= 0 ? `花了 ${paid} 金币删掉一张牌` : `删牌失败（code ${paid}）`, paid >= 0 ? "good" : "warn");
    this.refresh();
    return paid;
  }

  leave(): number {
    const code = this.host.leave();
    this.note(code === 0 ? "离开" : `离开被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：篝火 ────────────────────────────────────────────────────────────
  rest(): number {
    const code = this.host.rest();
    this.note(code === 0 ? `休息：回复 ${this.host.restHeal()} 点生命` : `休息被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  smith(index: number): number {
    const code = this.host.smith(index);
    this.note(code === 0 ? "锻造：升级了一张牌" : `锻造被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  toke(index: number): number {
    const code = this.host.toke(index);
    this.note(code === 0 ? "抽烟斗：删掉了一张牌" : `抽烟斗被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  lift(): number {
    const code = this.host.lift();
    this.note(code === 0 ? `举重：第 ${this.host.giryaLifts()} 次` : `举重被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  dig(): number {
    const before = this.host.relicIds();
    const code = this.host.dig();
    const after = this.host.relicIds();
    const fresh = after.filter((id) => !before.includes(id));
    this.note(code === 0 ? `挖到遗物：${fresh[0] ?? "（没有新的）"}` : `挖宝被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  recall(): number {
    const code = this.host.recall();
    this.note(code === 0 ? "拿到红钥匙" : `回忆被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：宝箱 ────────────────────────────────────────────────────────────
  /**
   * 打开宝箱。**打开即结束**（相位归 0），所以这里把增量记进 `lastLoot`。
   */
  openChest(): number {
    const before = decodeRun(this.host.runObservation());
    const relicsBefore = this.host.relicIds();
    const code = this.host.openChest();
    if (code === 0) {
      const after = decodeRun(this.host.runObservation());
      const relicsAfter = this.host.relicIds();
      const fresh = relicsAfter.filter((id) => !relicsBefore.includes(id));
      this.lastLoot = {
        gold: Math.max(0, after.gold - before.gold),
        relic: fresh[0] ?? "",
        source: "宝箱",
      };
      this.note(
        `打开宝箱：金币 +${this.lastLoot.gold}${this.lastLoot.relic ? ` · 遗物 ${this.lastLoot.relic}` : ""}`,
        "good"
      );
    } else {
      this.note(`打开宝箱失败（code ${code}）`, "warn");
    }
    this.refresh();
    return code;
  }

  /** 关掉战利品横幅。 */
  dismissLoot(): void {
    this.lastLoot = null;
    this.refresh();
  }

  // ── P4：事件 ────────────────────────────────────────────────────────────
  chooseEvent(slot: number): number {
    const code = this.host.choose(slot);
    this.note(code === 0 ? `事件：选了第 ${slot + 1} 项` : `事件选项被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  takeEventOffer(slot: number): number {
    const code = this.host.eventOfferTake(slot);
    this.note(code === 0 ? "事件：拿走了一张候选" : `拿候选失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  /** 事件问句的牌组下标答案（`Pending::EventCard`）。 */
  pickEventCard(index: number): number {
    const code = this.host.pickEventCard(index);
    this.note(code === 0 ? "事件：选了一张牌" : `事件选牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickBlessingCard(index: number): number {
    const code = this.host.pickBlessingCard(index);
    this.note(code === 0 ? "祝福：选了一张牌" : `祝福选牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：遗物欠账 ────────────────────────────────────────────────────────
  pickupPickCard(index: number): number {
    const code = this.host.pickupCard(index);
    this.note(code === 0 ? "遗物欠账：改了一张牌" : `改牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickupAddCard(slot: number): number {
    const code = this.host.pickupAddCard(slot);
    this.note(code === 0 ? "遗物欠账：加了一张牌" : `加牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickupSkip(): number {
    const code = this.host.pickupAddSkip();
    this.note(code === 0 ? "遗物欠账：跳过这一次" : `跳过被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  pickupMaxHp(): number {
    const code = this.host.pickupAddMaxHp();
    this.note(code === 0 ? "遗物欠账：换成生命上限 +2" : `换上限被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：药水 ────────────────────────────────────────────────────────────
  /**
   * 喝一瓶药水。
   *
   * ⚠️ `rd_env_use_potion` 的返回码：`0` 成功 / `-1` 没有这个槽 / `-2` 拒绝（带原因）。
   * 战斗外喝 run-only 的药水是**内核支持**的（§158），所以这里不按"在不在战斗"拦，
   * 由界面用 `needsFight` 决定画不画得动。
   */
  usePotion(slot: number, target: number): number {
    const code = this.host.usePotion(slot, target);
    const id = this.host.potionCount() > slot ? this.host.potionId(slot) : "";
    this.note(code === 0 ? `喝下 ${id || "药水"}` : `喝药水被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    // 战斗里喝药会改 148 格向量 ⇒ 战斗 store 也要重读（否则战斗屏还画着旧的）。
    this.combatStore?.refresh();
    this.refresh();
    return code;
  }

  dropPotion(slot: number): number {
    const id = this.host.potionCount() > slot ? this.host.potionId(slot) : "";
    const code = this.host.dropPotion(slot);
    this.note(code === 0 ? `扔掉 ${id || "药水"}` : `扔药水被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  /** 战斗中的牌堆（0 抽 / 1 弃 / 2 消耗）。没有战斗会话就返回空表。 */
  piles(): { zone: number; label: string; cards: { id: string; title: string }[] }[] {
    if (!this.host.hasCombatSession()) return [];
    const labels = ["抽牌堆", "弃牌堆", "消耗堆"];
    return [0, 1, 2].map((zone) => {
      const count = this.host.pileLen(zone);
      const cards: { id: string; title: string }[] = [];
      for (let index = 0; index < count; index += 1) cards.push(this.host.pileCard(zone, index));
      return { zone, label: labels[zone], cards };
    });
  }

  /** 局终后重开（保持同一 seed 便于复现，玩家可改）。 */
  restart(seed: number, ascension: number): void {
    this.startRun(seed, ascension);
  }
}
