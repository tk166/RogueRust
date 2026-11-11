// 探针：`window.__p1`。闸门 25 只通过它读语义，**不解析 DOM 结构**。
//
// 为什么要探针而不是让闸门点 DOM：3D 场景没有 DOM 可点（牌是 mesh），闸门必须知道
// "第 3 张牌此刻在屏幕上的哪个像素"。`layout` 是 3D 侧每帧投影出来的真值，闸门读它，
// 就等于"用渲染器自己的坐标系按下去"，不会出现"闸门和页面对布局的理解不一致"这种假绿。

import type { MachineStore } from "./store";
import type { ScreenLayout } from "./stage/layout";
import type { MockScene } from "./mock/scene";
import type { CommitLogEntry } from "./App";

export interface ProbeOptions {
  store: MachineStore;
  layout: ScreenLayout;
  scene: () => MockScene;
  commits: () => CommitLogEntry[];
  rebounds: () => string[];
  detailSlot: () => number;
  modalOpen: () => boolean;
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 只在 `?debug` 下存在：闸门需要造出"只剩一个敌人"的局面。 */
  debugSetEnemyHp?: (slot: number, hp: number) => void;
}

export interface Probe {
  ready: true;
  version: string;
  /** 构建时的源码指纹 + 参与指纹的文件数。 */
  srcHash: string;
  srcFiles: number;
  /** 状态机快照（phase / handSlot / hoverSlot / 合法落点表）。 */
  state: () => {
    phase: string;
    handSlot: number;
    hoverSlot: number;
    options: { slot: number; actionIndex: number; label: string }[];
    lastResult: unknown;
  };
  /** 卡牌与敌人在屏幕上的位置（CSS 像素）。闸门用它决定往哪儿按。 */
  layout: () => ScreenLayout;
  hand: () => { slot: number; id: string; name: string; cost: number; targeted: boolean; rules: string }[];
  enemies: () => { slot: number; name: string; hp: number; maxHp: number }[];
  hero: () => { hp: number; maxHp: number; block: number; energy: number; maxEnergy: number; turn: number };
  commits: () => CommitLogEntry[];
  rebounds: () => string[];
  detailSlot: () => number;
  modalOpen: () => boolean;
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 手牌文字的字号（闸门断言可读性用）。 */
  typeScale: () => Record<string, { title: number; rules: number }>;
  /** 帧率采样：在 `ms` 毫秒内数 rAF。headless 是软件光栅，数字只做记录，不当判据。 */
  fps: (ms?: number) => Promise<number>;
  /** ⚠️ **只在 `?debug` 下存在**：造局面（与旧页面 `?debug` 暴露 `givePotion` 同一纪律）。 */
  debug?: {
    setEnemyHp: (slot: number, hp: number) => void;
  };
}

/** 构建时烘进来的源码指纹（见 `vite.config.ts` 与 `scripts/src-hash.mjs`）。 */
declare const __SRC_HASH__: string;
declare const __SRC_FILES__: number;

export const PROBE_VERSION = "p1-mock-1";
/** 闸门用它判断"跑的是不是当前源码构建出来的包"（`dist/` 入库的代价）。 */
export const SRC_HASH = __SRC_HASH__;
export const SRC_FILES = __SRC_FILES__;

export function installProbe(options: ProbeOptions): void {
  const probe: Probe = {
    ready: true,
    version: PROBE_VERSION,
    srcHash: SRC_HASH,
    srcFiles: SRC_FILES,
    state: () => {
      const state = options.store.peek();
      return {
        phase: state.phase,
        handSlot: state.handSlot,
        hoverSlot: state.hoverSlot,
        options: state.options.map((option) => ({ ...option })),
        lastResult: state.lastResult,
      };
    },
    layout: () => ({
      cards: options.layout.cards.map((card) => ({ ...card })),
      enemies: options.layout.enemies.map((enemy) => ({ ...enemy })),
      width: options.layout.width,
      height: options.layout.height,
      frames: options.layout.frames,
    }),
    hand: () =>
      options.scene().hand.map((card, slot) => ({
        slot,
        id: card.id,
        name: card.name,
        cost: card.cost,
        targeted: card.targeted,
        rules: card.rules,
      })),
    enemies: () =>
      options.scene().enemies.map((enemy) => ({
        slot: enemy.slot,
        name: enemy.name,
        hp: enemy.hp,
        maxHp: enemy.maxHp,
      })),
    hero: () => {
      const hero = options.scene().hero;
      return {
        hp: hero.hp,
        maxHp: hero.maxHp,
        block: hero.block,
        energy: hero.energy,
        maxEnergy: hero.maxEnergy,
        turn: options.scene().turn,
      };
    },
    commits: () => options.commits().map((entry) => ({ ...entry })),
    rebounds: () => options.rebounds().slice(),
    detailSlot: () => options.detailSlot(),
    modalOpen: () => options.modalOpen(),
    openDetail: options.openDetail,
    setModal: options.setModal,
    typeScale: () => ({
      hand: { title: 11, rules: 0 },
      selected: { title: 15, rules: 12 },
      detail: { title: 20, rules: 14 },
    }),
    fps: (ms = 1000) =>
      new Promise<number>((resolve) => {
        let frames = 0;
        const start = performance.now();
        const tick = () => {
          frames += 1;
          if (performance.now() - start >= ms) {
            resolve((frames * 1000) / (performance.now() - start));
            return;
          }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
  };
  if (options.debugSetEnemyHp) {
    const setEnemyHp = options.debugSetEnemyHp;
    probe.debug = { setEnemyHp: (slot, hp) => setEnemyHp(slot, hp) };
  }
  (window as unknown as { __p1: Probe }).__p1 = probe;
}
