"""把 App.tsx（现在是 combat/CombatScreen.tsx）参数化：P3 的运行层复用它。"""

import io

P = 'web-next/src/combat/CombatScreen.tsx'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# 1) 文件头注释 + 组件签名
sub(
    '''// 应用外壳：Canvas + HUD + DOM 覆盖层 + 模态。
//
// **唯一权威是 `MachineStore`**：所有输入（鼠标/触摸/键盘/取消）都归一化成状态机事件再进去，
// 3D 组件不直接改局面（§纪律 2：一个元素一个写者；plan P1 的退出条件也要求
// "3D Card 渲染组件不直接调用 ex.rd_env_step"，P1 里对应的是"不直接改 scene"）。''',
    '''// **战斗屏**：Canvas + HUD + DOM 覆盖层 + 模态。
//
// 从 `App.tsx` 抽出来的（P3）。抽的理由是**闸门必须测到玩家真正在用的那一份**：
// P2 的闸门 28–32 打的是这个组件，P3 的玩家用的也是这个组件 —— 如果 P3 另写一份手势接线，
// 闸门就变成了"测另一份代码"，那是最坏的一种假绿（见 docs/port-plan.md §4 的工具形态）。
//
// **唯一权威是 `MachineStore`**：所有输入（鼠标/触摸/键盘/取消）都归一化成状态机事件再进去，
// 3D 组件不直接改局面（§纪律 2：一个元素一个写者；plan P1 的退出条件也要求
// "3D Card 渲染组件不直接调用 ex.rd_env_step"，P1 里对应的是"不直接改 scene"）。
//
// ## 两种用法
//
// | 用法 | `mode` | 谁提供 host | 行为 |
// |---|---|---|---|
// | P1/P2 回归（`index.html`） | `"auto"` / `"mock"` | 组件自己装载并走到第一场战斗 | 与 P2 完全一致 |
// | P3 运行层（`run.html`） | `"wasm"` | 外层 `RunStore` 给 | 不自动装载、不自动走路，战斗结束由外层收尾 |''',
    'header',
)

sub(
    '''export function App() {
  const store = useMemo(() => new MachineStore(), []);''',
    '''export interface CombatScreenProps {
  /**
   * `"auto"`：自己装载 wasm 并走到第一场战斗（P2 的回归行为，**不要改**）。
   * `"mock"`：确定局面（P1 的渲染/手势回归）。
   * `"wasm"`：由外层提供 `host` / `game`（P3 的运行层），本组件只负责这一场战斗。
   */
  readonly mode: "auto" | "mock" | "wasm";
  /** `mode === "wasm"` 时必须给：运行层的宿主（同一个 wasm 实例）。 */
  readonly host?: WasmHost;
  /** `mode === "wasm"` 时必须给：`RunStore` 持有的那个 `GameStore`。 */
  readonly game?: GameStore;
  /** `?mock` 的确定局面（P1 闸门用）；不给就是 `initialScene()`。 */
  readonly mockScene?: MockScene;
  /**
   * 战斗有结果之后玩家点"继续"时调用（P3 用它 `fight_end()` → 奖励屏）。
   *
   * ⚠️ 不给这个回调时**不显示**"继续"按钮：P2 的回归页没有下一屏，画一个死按钮
   * 就是 §4.22 那种"按类型点名的接口"。
   */
  readonly onFinish?: () => void;
}

export function CombatScreen(props: CombatScreenProps) {
  const store = useMemo(() => new MachineStore(), []);''',
    'signature',
)

# 2) MOCK_MODE 改为由 props 决定
sub(
    '''/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const MOCK_MODE = new URLSearchParams(window.location.search).has("mock");''',
    '''/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const URL_SAYS_MOCK = new URLSearchParams(window.location.search).has("mock");''',
    'mock const',
)

sub(
    '''  const [scene, setScene] = useState<MockScene>(() => debugScene(window.location.search));''',
    '''  /** Mock 侧的局面。`mode === "mock"` 时由 URL 造（P1 的 `?debug&enemies=N`）。 */
  const MOCK_MODE = props.mode === "mock" || (props.mode === "auto" && URL_SAYS_MOCK);
  const [scene, setScene] = useState<MockScene>(() =>
    props.mockScene ?? debugScene(window.location.search)
  );''',
    'mock scene state',
)

# 3) 装载 effect：`mode === "wasm"` 时直接用外层给的 host/game
sub(
    '''  useEffect(() => {
    if (MOCK_MODE) return;
    let cancelled = false;
    (async () => {''',
    '''  useEffect(() => {
    if (MOCK_MODE) return;
    // P3：外层（`RunStore`）已经装好并走到了战斗，这里**不**再装载、不再走路。
    if (props.mode === "wasm") {
      if (!props.host || !props.game) {
        setWasmError("运行层没有给 host/game：这是接线错误，不是内核问题");
        return;
      }
      setWasm({ host: props.host, game: props.game });
      return;
    }
    let cancelled = false;
    (async () => {''',
    'load effect',
)

sub(
    '''    return () => {
      cancelled = true;
    };
  }, []);''',
    '''    return () => {
      cancelled = true;
    };
    // `props.host` / `props.game` 在 P3 里是稳定的（由 RunStore 持有整个生命周期）。
  }, [props.mode, props.host, props.game, MOCK_MODE]);''',
    'load effect deps',
)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('CombatScreen parameterised')
