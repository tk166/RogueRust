# RogueRust 第十六轮 Review：素材流水线、表现系统与人工实操闭环

- **范围**：`ac6e2af5d1b1bc031bacbba35fd40774ed2d0baf^..32c0a208eb8951447d8e62d009eda1984b71699b`
- **基线**：终点 `32c0a208eb8951447d8e62d009eda1984b71699b`
- **审查方式**：指定提交序列的开发记录 + 终点版本关键源码定向静态审查；另以 Node 独立验证 FNV-1a 反例。**未获取完整 compare patch，未本地构建仓库或跑浏览器验收。**
- **范围原则**：区分源代码已确认的缺陷、未来扩展所需的架构缺口、已明确的有意简化；不把 UI 艺术质量等同于规则正确性。

## 0. 执行结论

**保留现有架构，局部修正并继续扩展。** 新 P8 素材管线 `内容镜像 -> build_assets.py -> manifest.ts -> registry.ts -> geometry.ts/Badge.tsx/EnemyFigure.tsx` 方向正确。ID 全覆盖、显式 fallback、纯函数测试、图鉴与真实截图门禁，是一个很好的 *visual availability layer*，但不是完整的 GLB/动画素材生产流水线，也未建立“某卡/某遗物触发特定动画”的来源语义。

### 修复优先级

| 级别 | 发现 | 影响 | 结论 |
|---|---|---|---|
| **P1** | `formation.ts` 使用旧要求将横屏 4 敌改回 **2+2** | 与用户后来明确的 **1–4 名敌人单排**新需求冲突 | 明确需求回归；应修正测试与注释 |
| **P2** | Python 与 JS 声称同一 FNV-1a，实则 32 位乘法和字符编码不同；敌人 palette 回退种子也不同 | 新内容/降级的外观跨生成器、运行时不一致 | 已独立复现 |
| **P2** | `ui_assets_check.mjs` 只核验逐项 ID、数据形状等，**未运行生成器等价性检查** | 改 palette/scale/boss 映射逻辑，旧 manifest 可能仍 PASS | 明确的门禁盲点 |
| **P2** | `gremlin_nob` 在 Python 的 Boss 特判名单中 | 该精英显示 Boss 光环、放大比例 | 有源代码证据的外观分类错误（除非为刻意特殊设计） |
| **P2（扩展前）** | BeatEffect 压缩成单个 `at` + `kind` + 文字 | 不能可靠还原 actor、target、卡/遗物/状态触发来源与动作链 | 未来专属动画的主要架构约束 |
| **P2（扩展前）** | 动画飘字根据**当前 slot 布局**定位，而不是事件发生瞬间的对象身份/锚点 | 召唤、分裂、死亡及重用槽位时可能出现位置错配 | 静态高置信风险，需实测 |
| P3 | `EnemyFigure.tsx` 使用静态 `parts`；无骨骼节点、GLB/clip、统一资源生命周期预算 | 16 原型可静态渲染但无法扩展复杂攻击 | 下一阶段的设计缺口，不是现有目标的运行 bug |
| P3 | Badge 是两字母且允许大规模碰撞 | 手牌与同类型图标辨认困难 | 占位可接受；不能声称最终美术覆盖 |

## 1. 本轮完整改动脉络与认可之处

**相关提交**（挑选主要里程碑）：
- `ac6e2af`：前次审查指出的 freeze / 模态重复 / 静态服务器路径及 SC-02b 等收尾。
- `3c62902`：P8 的内容 ID → 生成清单 → 注册表 → 16 程序化 3D 原型 / 2D Badge 流水线；素材预览页与两道门禁。
- `b6f891b`–`1ba68b6`：Boss 遗物过渡、归档版本、过幕幕帘、自动保存与回放输入输出。
- `a97238d`：首次实际人工操作暴露 styles.css 未载入和 UI 合成 ID 混入资源查询，修正后将卡牌资源查询改回内容 defId。
- `e04dbf0`–`6dfac67`：人工实操暴露地图镜像、死亡敌人残留、遗物/状态显示、悬停位置与点击不稳定、事件/目标语义等，陆续转入自动化门禁。
- `7d817a2`–`864f4f7`：选牌中文/详情、敌人意图、Slime Boss 分裂与动态预览等体验修补。
- `32c0a20`：商店单列、158 条状态说明、Boss 节点校验、真实分裂路径、手工存档字符串容错/回放辅助工具。

这些改动的共同价值，是将 *unit tests / CDP browsers / screenshots / 人工操作* 四种证据结合起来。建议将“首次手动验证”发展为每个修复附带的复现材料，而不仅是 `port-plan.md` 记录。

## 2. 已证实：横屏四名敌人布局回归（P1）

源码：[`web-next/src/stage/formation.ts#L70-L80`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/stage/formation.ts#L70-L80)

```ts
// 当前终点：
const singleRow = n <= 3;
const upperCount = singleRow ? n : Math.ceil(n / 2);
```

代码甚至注释了“第十四轮 Review P1-C”，把 4 个敌人单排认定为违反 `<=3` 老约束；然而用户此后专门澄清，**横屏四名及以下单排是新增需求**。这是审查意见没有随着产品要求更新导致的明确错误，不是用户改变主意造成的代码不稳。

**最小修复**：恢复 `const singleRow = n <= 4;`，继续使用 `n=5 => 3+2`、`n=6 => 3+3`。相应注释、单元测试、截图夹具全部更新。竖屏仍按右侧单列。若 4 个实体在特定狭窄横屏碰撞，应调整间距、模型尺寸或摄像机安全区，而**不能默默回退需求**。

**验收**：同一组 fixture 横屏 `n=1..6` 期望分别 `[1],[2],[3],[4],[3,2],[3,3]`；竖屏均单列；slot 身份不随排列变化。

## 3. 已证实：稳定哈希的 Python/JS 实现不同（P2）

Python：[`native/build_assets.py#L114-L120`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/build_assets.py#L114-L120)；JS：[`web-next/src/assets/registry.ts#L123-L131`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/assets/registry.ts#L123-L131)。

Python 每次遍历 **UTF-8 字节**，精确在 32bit 内乘法；JS 每次遍历 `charCodeAt` 的 **UTF-16 code unit**，且用浮点 `value * prime` 再 `>>>0`，不是精确的 32bit 乘法：

```ts
// 建议替换运行时哈希，用 Math.imul 和 UTF-8 对齐 Python：
function stableHash(text: string): number {
  let value = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    value = Math.imul(value ^ byte, 0x01000193) >>> 0;
  }
  return value >>> 0;
}
```

**独立 Node 验证结果**：

| 输入 | 当前 JS | 正确 FNV-1a 32bit | 当模 16 用于原型时 |
|---|---:|---:|---|
| `not_a_real_enemy` | 1294215100 | 2453344752 | 12 vs 0 |
| `new_monster_id` | 116679432 | 2615040844 | 8 vs 12 |
| `strike` | 2778783723 | 632598351 | 11 vs 15 |
| `中文` | 1362277804 | 3297308741 | 12 vs 5 |

此外：生成器的敌人 **palette** 是 `stable_hash(monster_id + '|p') % PALETTES`，JS 未知敌人 fallback 却用 `stableHash(id) % PALETTES`，即使修复乘法仍不一致。参考 [`native/build_assets.py#L144-L165`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/build_assets.py#L144-L165) 与 [`registry.ts#L34-L38`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/assets/registry.ts#L47-L50)。

**影响范围**：对已有 manifest 中的已知 ID 大部分不构成运行时错误；对新 ID、清单过期、unknown fallback 及跨语言生成一致性构成确切差异。不要误报“所有 61 个敌人都显示错误”。

**验收**：抽取一组 ASCII/Unicode/空串输入，Python 和 JS FNV、原型和 palette 逐项相等；再删除一个已知 ID 测试 fallback 且 unknown 计数正确。

## 4. 素材门禁验证的是覆盖，不是生成器输出等价性（P2）

[`native/ui_assets_check.mjs#L53-L84`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/ui_assets_check.mjs#L53-L84) 直接说明未在门禁运行 `python native/build_assets.py --check`，改为检查逐项 ID。**这能抓住增删内容之后未更新清单，但抓不到生成器修改了 palette、scale 或 boss 规则而 manifest 未更新**。

不建议强制所有接受脚本在 PATH 中寻找 `python`，可以在构建工具层选择显式 Python 可执行路径，单独执行 `--check`；或让生成器输出 `schemaVersion + generatorFingerprint + contentFingerprint`，再做 golden 输出比对。推荐前者用于 release/CI、后者用于快速开发门禁。更重要的是对 *generated values* 做检验，不只判断 key 存在。

另一个语义边界：生成器必然给全部 ID 分配占位，所以“61/295/152/33/150 ID 齐全”应称为 **placeholder coverage**，后续区分 `kind:'procedural'|'gltf'`, `tier:'placeholder'|'custom'`, `source/license/hash`，统计原型与定制美术覆盖率，不应因为回退总能成功就报告“素材已制作完成”。

## 5. 小型外观分类错误：Gremlin Nob 被提升为 Boss（P2）

[`native/build_assets.py#L144-L165`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/build_assets.py#L144-L165) 中，`gremlin_nob` 被加入强制 Boss 集合，因而触发 `scale=1.55` 与 `boss=true`；[`EnemyFigure.tsx#L72-L80`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/stage/EnemyFigure.tsx#L72-L80) 对 Boss 添加光环。StS1 的 Gremlin Nob 是精英（Elite），不是 Boss。

若确实想把它放大以强化威胁感，应使用独立 `visualScaleOverride` 或 `threatStyle`, **不要把视觉体型和玩法身份混成一个 `boss` 布尔值**。新增 `tier=elite,boss` 的测试，并重新生成清单。

## 6. 未来扩展的关键边界：VisualAssetRegistry ≠ PresentationRegistry

当前 [`web-next/src/assets/geometry.ts`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/assets/geometry.ts) 只保存静态 `{shape,size,position,rotation,role}`，[`EnemyFigure.tsx`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/stage/EnemyFigure.tsx) 负责渲染；没有完整的骨骼挂点、攻击 clip、状态 VFX 或动作语义。

当前 [`web-next/src/combat/beats.ts#L31-L40`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/combat/beats.ts#L31-L40) 的 `BeatEffect` 只有 `id,kind,at,text,tone,duration`，上游 Beat 其实具有 `actor,target,flags,a,b,c,def`。`planBeats` 在转化时丢掉了大部分因果信息。它足够产生飘字，却不足以根据可靠 ID 决定“Strike 的斩击 vs Bash 的重击”、“Orichalcum 格挡触发 vs 普通 Defend 格挡”或“毒素持续伤害 vs 卡牌直接伤害”。

**不要以文本、数值、颜色或 current HP diff 反推原因。** 推荐增加一个*只读的表现描述层*：

```ts
// 建议模型，不是现有 WASM ABI。
type Origin =
  | { kind: 'card'; defId: string; instanceId?: string }
  | { kind: 'relic'; defId: string }
  | { kind: 'status'; defId: string }
  | { kind: 'enemyMove'; defId: string }
  | { kind: 'system' };

type PresentationCue = {
  eventId: number;
  actionId?: number;
  origin?: Origin;
  kind: 'attack'|'damage'|'block'|'heal'|'status'|'spawn'|'death'|'trigger';
  actor?: { slot: number; appearanceId?: string };
  target?: { slot: number; appearanceId?: string };
  value?: number;
  effectKey: string;          // 解析为一段视觉配方
  anchor?: [number, number, number]; // 在事件时间点冻结的表现锚点
  phase?: 'cast'|'hit'|'resolve';
};
```

**注意：`origin` 不能凭空生成。** 第一版从可确定的当前玩家 Action/卡牌 ID 与确有意义的 Beat.def 建立因果上下文；无法证明的触发保留 `origin:system` 或 undefined。挑选一个确实无法从现有事件中恢复来源的遗物触发例子，再最小化扩展 Rust Beat（仅加语义字段，不把视觉配置塞进内核）。避免一开始为全套卡牌设计一棵大型万能动画 DSL。

### 建议的播放层次

- `GameSnapshot / GameBeat`：规则与事件事实，仍由 Rust 权威负责。
- `CueTranslator`：纯函数；输入 Beat、动作上下文和事件时快照，输出语义 Cue；失败可诊断、可降级。
- `PresentationRegistry`：映射 `effectKey`/`origin.defId` 到可组合视觉预设（攻击轨迹、粒子、受击材质闪烁、GLB clip、HUD 图标）；内容驱动、显式优先级和 fallback。
- `PresentationDirector`：时间轴分阶段调度；同一 action 下可串行 cast→hit→resolve，独立飘字/粒子可并行，保留 skip、reducedMotion、未知反馈可见。
- `ActorRenderer`：读取 `VisualAssetRegistry`，程序化原型或 GLB 依统一接口渲染，带命名挂点（body/head/weapon/impact/statusRoot）。

### 两个需要避免的技术陷阱

1. **单一位置槽位不是稳定身份**：`BeatLayer.tsx` 的 [`anchorOf`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/combat/BeatLayer.tsx#L20-L27) 在播放时用当前 `layout.enemies.find(slot)` 取位置。若 Boss 分裂、召唤、死亡及 slot 重用，队列里较早 Beat 可能被画在新对象头顶。建议 Cue 创建时绑定 `appearanceId` 或事件时锚点。现阶段只是状态序列可推导的风险，须通过真实 Slime Boss 分裂 E2E 验证。
2. **不要硬写所有动画为单一队列**：目前 `DirectorState` 一条 `playing` 串行加尾队列设计适合文字；引入斩击/VFX 后可按时间锚与轨道调度，仍需保持消费顺序和动画跳过时规则完全不变。

## 7. GLB 演进：保留程序化回退，增量增加真正的动画资产

现在文档写“将 `geometry.parts` 换成 `{model, clips}`”，作为方向无妨，但直接替换 `Archetype` 会迫使 `EnemyFigure` 改写数据契约；更稳妥是增加带 `kind` 的判别联合：

```ts
type VisualAssetSpec =
  | { kind: 'procedural'; archetype: string; paletteId: number; scale: number }
  | { kind: 'gltf'; url: string; clips: Record<string, string>; scale: number;
      sockets?: Record<'head'|'hand'|'impact'|'status', string>; sha256?: string };
```

由 `ActorRenderer` 根据 `kind` 选择 `ProceduralEnemy` / `GltfEnemy`。对 `useGLTF`/Texture 缓存、`AnimationMixer`/clip 分配、挂点查找和释放建立最小可验证生命周期。不要把 61 名敌人全部改为 GLB，先挑低成本的两个代表体型（Cultist 和 Slime/Guardian），逐步引入。

为每个正式素材记录来源/许可证/制作版本/sha256/LOD/预估传输和运行内存，在预览页建立“真实模型 + fallback + 缺 clip”报告。程序化 3D 仍是很好的移动端和资源异常时降级。

## 8. 实操反馈应该如何变成正式可回归机制

本轮人工操作找到的 bug 很有价值；接下来可让 Agent 每次提交修复时附：

```text
commit = ...
wasm_sha256 = ...
content_fingerprint = ...
replay_or_save = ...
seed + act/node/room + exact steps = ...
viewport_css_px + DPR + OS/browser/device = ...
expected / actual = ...
screenshot or short video = ...
regression_gate = ...
```

推荐优先真实测试：地图点选保持对称、hover 卡牌区域不改变自身布局、商店可以选中所有项目、同种卡多次连续出牌、Slime Boss 分裂的 actor/target 锚点、毒/格挡/遗物触发与日志/飘字同因果、触摸 `pointercancel` 不产生幽灵动作、手工归档刷新及真实 replay 路径。

不要把“CDP 元素存在”当成“CSS/资源已加载”，也不要把“屏幕上有彩色像素”当作“显示的角色与 content ID 一致”。每类门禁各守自己的故障模式。

## 9. 下一轮最小实施顺序

| 里程碑 | 代码范围 | 验收 |
|---|---|---|
| **R0 正确性** | `formation.ts`、`registry.ts`、`build_assets.py`、`ui_assets_check.mjs` | 4 名横屏单排；Python/JS 映射 parity；精英 ≠ Boss；生成器变值过期时门禁 FAIL |
| **R1 表现契约** | 新增 `presentation/cues.ts`, `presentation/registry.ts`，少量测试 | 基于真实 Beat 实现 Strike、Bash、Defend、毒和一个遗物；缺 source 明示 unknown，不猜测 |
| **R2 动画原型** | `ActorRenderer`/Drei Trail/Three.js，保留现有 BeatLayer | cast/hit/resolve、目标锚点和 slot 重用；skip/reducedMotion 不改游戏状态 |
| **R3 GLB 渐进式** | 两个代表敌人 GLB + sockets + clip 加载；预览页 | fallback 不丢失；资源缓存和卸载、断网/缺 clip、移动端体积有证据 |
| **R4 产品扩展** | card/relic/status 的 PresentationRegistry 数据文件、可视化画廊 | 新增一种卡/状态/敌人或遗物触发，原则上无需修改 `Stage.tsx`/`EnemyFigure.tsx`/主导演 |

**最终建议**：先修 P1 的四敌队形回归和 P2 的哈希/门禁；再用几种真实动作构建 `PresentationCue + PresentationRegistry` 垂直切片；最后让 GLB/粒子/材质作为可替换的动画执行器接入。不要在这轮直接为每个内容 ID 扩充一个专用组件，也不要为尚无证据的动画需求重构 Rust 规则层。

## 10. 审查证据与限制

源码固定版本：
- [`formation.ts`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/stage/formation.ts)
- [`native/build_assets.py`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/build_assets.py)
- [`assets/registry.ts`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/assets/registry.ts)
- [`assets/geometry.ts`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/assets/geometry.ts)
- [`stage/EnemyFigure.tsx`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/stage/EnemyFigure.tsx)
- [`combat/beats.ts`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/combat/beats.ts)
- [`combat/BeatLayer.tsx`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/web-next/src/combat/BeatLayer.tsx)
- [`native/ui_assets_check.mjs`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/native/ui_assets_check.mjs)
- [`docs/ui-p8-assets.md`](https://github.com/tk166/RogueRust/blob/32c0a208eb8951447d8e62d009eda1984b71699b/docs/ui-p8-assets.md)

本人**仅独立运行了 Node 哈希反例**，并非对当前仓库独立构建。项目声称门禁 56 道全通过，尚未经本人复验。以上是有边界的定向源码审查，不等价完整 diff 逐行审核或真机可用性认证。
