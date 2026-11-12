# P5 Beat 演出与资源降级

> 代码：`web-next/src/combat/beats.ts`（纯导演）、`BeatLayer.tsx`（DOM 飘字）、
> `web-next/src/stage/assets.ts`（外观表 + 降级）。闸门 37（纯函数）与 38（端到端）。

## 1. 数据流

```
内核 rd_env_beat_*（kind 1–13）
        │  GameStore.dispatch 记住 lastBeats + seq（两条 dispatch 路径共用）
        ▼
planBeats(beats, dropped) ──► BeatEffect[]（tone / text / at / duration）
        │
        ▼  enqueue（不打断正在播的那条）
advance(state, dtMs) ◄── rAF（`last` 在 ref 里）
        │
        ▼
BeatLayer：DOM 飘字，坐标来自 layout（与 3D 同一套投影）
```

## 2. 三条结构性保证

| 保证 | 为什么成立 |
|---|---|
| 播放动画的**最终状态与内核一致** | 演出层**不持有状态**：它只读 beat、只产出飘字。局面永远来自内核观察向量 |
| **关闭动画也能完整游戏** | 关动画 = `reducedMotion` ⇒ 队列一条都不入，不是另一条代码路径 |
| **动画不卡住待决流程** | 演出是 `pointer-events: none` 的覆盖层；下一条动作与动画播放无关 |

## 3. 降级（plan 明确要求的三条）

| 情况 | 行为 |
|---|---|
| 未知 beat kind | 降级成中性 `?N` 飘字 + **计数**（`unknownKinds`），永不抛 |
| 内核丢 beat（`dropped > 0`） | 界面上挂一条"动画不全（丢了 N 条）" |
| 未知 enemyId | `enemyLook()` 返回 `placeholder` + 计数（`unknownEnemyAssets()`） |

## 4. 跳过与快进

* 队列非空时右下角有"跳过（Esc）"按钮；Esc 也走同一个 `skipAll`。
* `skipAll` **不清账**：`dropped`/`unknownKinds` 仍然保留（跳过的是动画，不是事实）。
* 快进 = 一次 `advance(state, 很大的 dt)`：余量会**结转**给下一条（慢帧率下动画不会拖长）。

## 5. 三个实测坑（都是"看起来像动画没跑"）

1. **无头 Chrome 的 `prefers-reduced-motion` 是 `reduce`** ⇒ 闸门里默认不播。
   "动画开着"必须 `?motion=on` 显式要求。
2. **rAF 的 `last` 写在 effect 闭包里**：依赖是 `director`、每帧重建 effect，于是它被重置成
   "现在"、`dt` 恒 0、`elapsed` 恒 0（卡在第一帧）。必须放 **ref**。
3. **探针闭包捕获旧 state**：`beats()` 若捕获 `installProbe` 那一刻的 `director`，会永远返回
   旧快照。必须读 **ref**。

## 6. 明确没做

**GLB 角色与 AssetRegistry**（plan P5 的第二条）。这一版没有资产管线，所以只做了
"表 + 降级"：写一个假加载器会让"资产缺失"看起来像"资产有了"。
