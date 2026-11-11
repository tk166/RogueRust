"""P2 第二步（2/3）：`Stage` / `TextOverlay` / 探针的类型从 `MockScene` 换成 `CombatView`。

渲染层不该知道数据来自 Mock 还是 wasm —— 这是第二步的核心。字段名刻意一致，所以这里只改
类型与 import，**不动任何渲染逻辑**（少改一行就少一个"顺手改坏"的机会）。
"""

import io

STAGE = 'web-next/src/stage/Stage.tsx'
OVERLAY = 'web-next/src/overlay/TextOverlay.tsx'
PROBE = 'web-next/src/probe.ts'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    STAGE,
    '''import type { MockScene } from "../mock/scene";''',
    '''import type { CombatView } from "../view/combatView";''',
    'stage import',
)

edit(
    STAGE,
    '''  scene: MockScene;''',
    '''  /** 渲染层只认识 `CombatView`：Mock 与真 wasm 都由生产者适配成这个形状。 */
  scene: CombatView;''',
    'stage prop type',
)

edit(
    OVERLAY,
    '''import type { MockCard, MockScene } from "../mock/scene";''',
    '''import type { CombatView, ViewCard } from "../view/combatView";''',
    'overlay import',
)

edit(
    OVERLAY,
    '''  scene: MockScene;''',
    '''  scene: CombatView;''',
    'overlay prop type',
)

edit(
    OVERLAY,
    '''function DetailCard({ card, onClose }: { card: MockCard; onClose: () => void }) {''',
    '''function DetailCard({ card, onClose }: { card: ViewCard; onClose: () => void }) {''',
    'overlay detail type',
)

# 探针：加 view / mode / wasm 诊断 / endTurn
edit(
    PROBE,
    '''import type { MockScene } from "./mock/scene";''',
    '''import type { MockScene } from "./mock/scene";
import type { CombatView } from "./view/combatView";
import type { WasmDiagnostics } from "./wasm/host";''',
    'probe imports',
)

edit(
    PROBE,
    '''  scene: () => MockScene;''',
    '''  scene: () => MockScene;
  /** 渲染层实际拿到的视图（Mock 或 wasm 适配后的）。 */
  view: () => CombatView;
  mode: () => "mock" | "wasm";
  wasmDiagnostics: () => WasmDiagnostics | null;
  wasmError: () => string | null;
  /** 结束回合（wasm 侧走内核动作；Mock 侧只推进回合数）。 */
  endTurn: () => { accepted: boolean; code: number | null };''',
    'probe options type',
)

edit(
    PROBE,
    '''  /** 手牌文字的字号（闸门断言可读性用）。 */''',
    '''  /** 渲染层实际拿到的视图。 */
  view: () => {
    mode: string;
    hero: { hp: number; hpMax: number; block: number; energy: number; maxEnergy: number };
    hand: { id: string; name: string; cost: number | "X"; targeted: boolean; playable: boolean }[];
    enemies: { slot: number; name: string; hp: number; hpMax: number; alive: boolean; intent: string }[];
    turn: number;
    round: number;
    result: string;
  };
  /** `?mock` ⇒ mock，否则 wasm。 */
  mode: () => "mock" | "wasm";
  wasmDiagnostics: () => WasmDiagnostics | null;
  wasmError: () => string | null;
  endTurn: () => { accepted: boolean; code: number | null };
  /** 手牌文字的字号（闸门断言可读性用）。 */''',
    'probe interface',
)

edit(
    PROBE,
    '''    hovered: () => ({ card: options.hoveredCard(), enemy: options.hoveredEnemy() }),''',
    '''    hovered: () => ({ card: options.hoveredCard(), enemy: options.hoveredEnemy() }),
    view: () => {
      const view = options.view();
      return {
        mode: view.mode,
        hero: { ...view.hero },
        hand: view.hand.map((card) => ({
          id: card.id,
          name: card.name,
          cost: card.cost,
          targeted: card.targeted,
          playable: card.playable,
        })),
        enemies: view.enemies.map((enemy) => ({
          slot: enemy.slot,
          name: enemy.name,
          hp: enemy.hp,
          hpMax: enemy.hpMax,
          alive: enemy.alive,
          intent: enemy.intent,
        })),
        turn: view.turn,
        round: view.round,
        result: view.result,
      };
    },
    mode: options.mode,
    wasmDiagnostics: options.wasmDiagnostics,
    wasmError: options.wasmError,
    endTurn: options.endTurn,''',
    'probe impl',
)
print('types switched to CombatView')
