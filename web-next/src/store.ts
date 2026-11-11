// 极小的外部 store：把纯状态机接到 React 上，**不引入状态库**。
//
// `useSyncExternalStore` 的约定是"快照必须是同一个对象引用直到真的变了"，所以 `send()` 只在
// `reduce` 返回新对象时才通知。P1 的每帧投影不走这里（那是 60Hz，走 rAF 直接改 DOM）。

import { INITIAL, reduce, type Event as MachineEvent, type State } from "./input/pointerMachine";

type Listener = () => void;

export class MachineStore {
  private current: State = INITIAL;
  private readonly listeners = new Set<Listener>();

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): State => this.current;

  send(event: MachineEvent): State {
    const next = reduce(this.current, event);
    if (next === this.current) return next;
    this.current = next;
    for (const listener of this.listeners) listener();
    return next;
  }

  /** 供探针/闸门读取，不触发通知。 */
  peek(): State {
    return this.current;
  }
}
