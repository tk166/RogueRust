"""P2 第二步（1/3）：App 改成"双引擎" —— `?mock` 走 Mock，默认走真 wasm。

## 为什么两条路并存

P1 的 94 条浏览器断言全部建立在"确定的 10 张牌 / 2 个敌人"上。换成真 wasm 之后那些断言的
**含义**会变（牌是随机的、敌人血会变）。所以：
* `?mock` —— 确定局面，守 P1 的渲染与手势回归；
* 默认 —— 真 wasm，守 P2 的数据源回归（UI 必须与内核一致）。

## 提交路径

`applyCommit`（Mock 自己结算）保留给 mock；wasm 侧走 `store.dispatch(action)`：
动作来自内核动作表（`state.options` 里就带着 `actionIndex`），拒绝时**不演出成功**。
"""

import io

PATH = 'web-next/src/App.tsx'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── ① imports ─────────────────────────────────────────────────────────────
sub(
    '''import { initialScene, liveEnemySlots, type MockCard, type MockScene } from "./mock/scene";''',
    '''import { initialScene, liveEnemySlots, type MockCard, type MockScene } from "./mock/scene";
import { viewFromMock, viewFromWasm, type CombatView } from "./view/combatView";
import { WasmHost } from "./wasm/host";
import { GameStore } from "./wasm/store";''',
    'imports',
)

# ── ② 引擎状态 ────────────────────────────────────────────────────────────
sub(
    '''export function App() {
  const store = useMemo(() => new MachineStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [scene, setScene] = useState<MockScene>(() => debugScene(window.location.search));''',
    '''/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const MOCK_MODE = new URLSearchParams(window.location.search).has("mock");

export function App() {
  const store = useMemo(() => new MachineStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [scene, setScene] = useState<MockScene>(() => debugScene(window.location.search));
  /** 真 wasm 的宿主与商店；`null` = 还没装载好（或装载失败）。 */
  const [wasm, setWasm] = useState<{ host: WasmHost; game: GameStore } | null>(null);
  const [wasmError, setWasmError] = useState<string | null>(null);
  /** wasm 侧的视图；Mock 侧由 `scene` 派生。 */
  const [wasmView, setWasmView] = useState<CombatView | null>(null);''',
    'engine state',
)

# ── ③ 视图派生 ────────────────────────────────────────────────────────────
sub(
    '''  const liftedSlot = state.phase === "idle" ? -1 : state.handSlot;''',
    '''  const liftedSlot = state.phase === "idle" ? -1 : state.handSlot;

  // ── 视图：渲染层只认识 `CombatView`，不关心数据来自 Mock 还是 wasm ─────────
  const view: CombatView = useMemo(
    () => (MOCK_MODE || !wasmView ? viewFromMock(scene) : wasmView),
    [scene, wasmView]
  );

  // 装载真 wasm：开局 → 走到战斗 → 建 store。失败就把诊断显示出来（**不进入半可用**）。
  useEffect(() => {
    if (MOCK_MODE) return;
    let cancelled = false;
    (async () => {
      try {
        const host = await WasmHost.load("./rd_wasm.wasm");
        if (cancelled) return;
        // 固定种子 + 固定的走路方式：同一个构建 ⇒ 同一场战斗（闸门要可复现）。
        host.startRun(1, 0);
        for (let hop = 0; hop < 40; hop += 1) {
          const raw = host.runRaw();
          if (raw.over === 1) break;
          if (raw.pending === 0) {
            if (raw.nodeKind >= 0 && raw.nodeResolved === 0) {
              const isFight = raw.nodeKind === 1 || raw.nodeKind === 2 || raw.nodeKind === 7;
              if (isFight) break;
              host.beginNode();
              continue;
            }
            if (host.runStep(0) !== 0) break;
            continue;
          }
          if (!host.settlePendingRun()) break;
        }
        if (host.fightBegin() !== 0) throw new Error("fight_begin 被拒绝");
        const game = new GameStore(host);
        if (cancelled) return;
        setWasm({ host, game });
        setWasmView(viewFromWasm(game.getSnapshot()!, host));
      } catch (error) {
        if (!cancelled) setWasmError(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 每次内核状态变化就重建视图（`dispatch` 之后 store 会通知）。
  useEffect(() => {
    if (!wasm) return;
    const rebuild = () => {
      const snapshot = wasm.game.getSnapshot();
      setWasmView(snapshot ? viewFromWasm(snapshot, wasm.host) : null);
    };
    rebuild();
    return wasm.game.subscribe(rebuild);
  }, [wasm]);''',
    'view derivation',
)

# ── ④ 提交：按引擎分派 ────────────────────────────────────────────────────
sub(
    '''    if (result.kind === "commit") {
      const card = scene.hand[result.handSlot];
      applyCommit({
        handSlot: result.handSlot,
        actionIndex: result.actionIndex,
        targetSlot: result.targetSlot,
        card: card ? card.id : "?",
      });
      setDetailSlot(-1);
      flash("已出牌 · 动作已提交", "success");
    } else {''',
    '''    if (result.kind === "commit") {
      const card = view.hand[result.handSlot];
      if (MOCK_MODE || !wasm) {
        applyCommit({
          handSlot: result.handSlot,
          actionIndex: result.actionIndex,
          targetSlot: result.targetSlot,
          card: card ? card.id : "?",
        });
        flash("已出牌 · 动作已提交", "success");
      } else {
        // 真 wasm：动作表里的 `actionIndex` 就是 `rd_env_step` 的入参，**不要**自己再映射一层。
        const action = wasm.game
          .actions()
          .find((candidate) => candidate.index === result.actionIndex) ?? null;
        if (!action) {
          // 内核没给这条动作 ⇒ 不是"玩家操作非法"，是"UI 与内核不同步"。响亮失败。
          flash("动作已过期 · 状态未改变", "warning");
        } else {
          const outcome = wasm.game.dispatch(action);
          if (outcome.accepted) flash("已出牌 · 动作已提交", "success");
          else flash("内核拒绝了这一步 · 状态未改变", "warning");
        }
      }
      commits.current.push({
        handSlot: result.handSlot,
        actionIndex: result.actionIndex,
        targetSlot: result.targetSlot,
        card: card ? card.id : "?",
      });
      setDetailSlot(-1);
    } else {''',
    'commit branch',
)

sub(
    '''  }, [state.lastResult, state.resultSeq, scene.hand, applyCommit, flash]);''',
    '''  }, [state.lastResult, state.resultSeq, view.hand, applyCommit, flash, wasm]);''',
    'commit deps',
)

# ── ⑤ onCardDown：落点表来自视图 ──────────────────────────────────────────
sub(
    '''      const card = scene.hand[slot];
      if (!card) return;''',
    '''      const card = view.hand[slot];
      if (!card) return;''',
    'onCardDown card',
)

sub(
    '''      store.send({ type: "down", handSlot: slot, options: optionsFor(card, scene, slot) });''',
    '''      // ⚠️ 落点表来自**视图**（wasm 那边就是内核动作表），UI 不自己推"能不能打这个敌人"。
      store.send({ type: "down", handSlot: slot, options: view.optionsFor(slot) });''',
    'onCardDown options',
)

sub(
    '''    [modalOpen, scene, store, flash]''',
    '''    [modalOpen, view, store, flash]''',
    'onCardDown deps',
)

# ── ⑥ 探针 / 渲染：把 scene 换成 view ─────────────────────────────────────
sub(
    '''      scene: () => scene,''',
    '''      scene: () => scene,
      view: () => view,
      mode: () => (MOCK_MODE ? "mock" : "wasm"),
      wasmDiagnostics: () => (wasm ? wasm.host.diagnostics : null),
      wasmError: () => wasmError,
      endTurn: () => {
        if (MOCK_MODE || !wasm) {
          setScene((current) => ({ ...current, turn: current.turn + 1 }));
          return { accepted: true, code: 0 };
        }
        const option = wasm.game.findEndTurn();
        if (!option) return { accepted: false, code: null };
        const outcome = wasm.game.dispatch(option);
        return { accepted: outcome.accepted, code: outcome.code };
      },''',
    'probe view',
)

sub(
    '''  }, [store, scene, detailSlot, modalOpen, hoverCardSlot, hoveredEnemySlot, onDetail]);''',
    '''  }, [store, scene, view, wasm, wasmError, detailSlot, modalOpen, hoverCardSlot, hoveredEnemySlot, onDetail]);''',
    'probe deps',
)

sub(
    '''          scene={scene}
          liftedSlot={liftedSlot}''',
    '''          scene={view}
          liftedSlot={liftedSlot}''',
    'stage scene prop',
)

sub(
    '''          hp={scene.hero.hp}
          maxHp={scene.hero.maxHp}
          block={scene.hero.block}
          energy={scene.hero.energy}
          maxEnergy={scene.hero.maxEnergy}
          turn={scene.turn}''',
    '''          hp={view.hero.hp}
          maxHp={view.hero.hpMax}
          block={view.hero.block}
          energy={view.hero.energy}
          maxEnergy={view.hero.maxEnergy}
          turn={view.turn}''',
    'hud props',
)

sub(
    '''          onEndTurn={() => {
            setScene((current) => ({ ...current, turn: current.turn + 1 }));
          }}''',
    '''          onEndTurn={() => {
            if (MOCK_MODE || !wasm) {
              setScene((current) => ({ ...current, turn: current.turn + 1 }));
              return;
            }
            const option = wasm.game.findEndTurn();
            if (option) wasm.game.dispatch(option);
          }}''',
    'hud end turn',
)

sub(
    '''      <TextOverlay scene={scene} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    '''      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    'overlay scene prop',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('App: dual engine')
