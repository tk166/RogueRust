"""多进程向量化环境 —— 观察经**共享内存**传递，不走 IPC。

## 为什么重写

上一版每步把一个 `n_envs × 122` 的观察经 `Pipe` pickle 往返，实测：

```
单进程 4 句柄（无 IPC）      :   5,911 步/秒
1 进程 × 4 句柄（走 IPC）    :     227 步/秒      ← 慢 26 倍
8 进程 × 4 句柄 = 32 env     :   1,125 步/秒
```

IPC 完全主导了开销：8 进程 × 4 环境 × 122 个整数 ≈ 每步 3,900 个整数被序列化，
"多开"的收益被通信成本吃光还倒亏。

`docs/spec/env-abi.md` §2 把观察定成**定长整数向量**，本来就是为了能**直接放进一块连续内存**。
上一版把定长的好处拿到了，却仍然按 Python 对象搬运 —— 这是包装层的错，不是 ABI 的错。

## 现在的做法

父进程开一块 `shared_memory`，布局 `int32[n_envs × STRIDE]`，`STRIDE = observe_len + 2`
（每环境：观察 + 奖励 + done）。每个 worker 把结果**直接写进自己那段**，
IPC 只回一个 `("ok",)` 同步信号 —— **每步搬运的字节数从约 3,900 个整数降到 0**。

## 两条保留的设计

* **每 worker 持多个句柄**：跨进程同步有固定成本，一进程一句柄会让它变成瓶颈。
* **reset 换种子 = 重建句柄**：句柄式 ABI 的既定语义（`env-abi.md` §3），包装层不自创。
"""

from __future__ import annotations

import array
import multiprocessing as mp
import os
import sys
import traceback
from multiprocessing import shared_memory
from typing import Any, List, Optional, Sequence, Tuple

from .env import RogueDeckEnv
from .native import EnvABI

# spawn 出来的子进程要能 `import roguedeck_env`，而**不依赖父进程当时的 cwd**。
# sys.path 是在 `Process.start()` 那一刻被复制给子进程的，所以这里（导入期）补上就来得及。
# 不补的话，从别处 `python -m` 或者 cwd 变了就会得到一个"子进程静默消失"的现场 —— 极难查。
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

# 每环境的槽位数：观察 + 奖励 + done
_EXTRA = 2


def _stride(observe_len: int) -> int:
    return observe_len + _EXTRA


def _worker(conn, shm_name: str, base_env: int, config: int, envs_per_worker: int,
            base_seed: int, epoch: int, auto_reset: bool) -> None:
    """worker 入口。**任何异常都必须先报给父进程再死** —— 静默消失是最贵的失败模式。"""
    try:
        _worker_impl(conn, shm_name, base_env, config, envs_per_worker, base_seed, epoch,
                     auto_reset)
    except BaseException:  # noqa: BLE001
        tb = traceback.format_exc()
        sys.stderr.write(f"[vec worker pid={os.getpid()}] 崩溃:\n{tb}\n")
        sys.stderr.flush()
        try:
            conn.send(("error", f"worker pid={os.getpid()} 崩溃:\n{tb}"))
        except Exception:  # noqa: BLE001
            pass  # 管道也断了：stderr 已经留下证据
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _worker_impl(conn, shm_name: str, base_env: int, config: int, envs_per_worker: int,
                 base_seed: int, epoch: int, auto_reset: bool) -> None:
    """worker 主循环。观察写共享内存，IPC 只传同步信号。"""
    try:
        abi = EnvABI()
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"worker pid={os.getpid()} 加载 ABI 失败: {exc}"))
        conn.close()
        return

    shm = shared_memory.SharedMemory(name=shm_name)
    stride = _stride(abi.observe_len())
    view = memoryview(shm.buf).cast("i")
    # 复用的中转缓冲：一次 bulk observe 填它，再整段拷进共享内存。多一次 488 B 的 memcpy，
    # 换掉的是 122 次跨 ABI 调用（实测 40 µs/步）。
    stage = array.array("i", bytes(abi.observe_len() * 4))

    envs: List[RogueDeckEnv] = []
    try:
        for k in range(envs_per_worker):
            seed = base_seed + epoch * 1_000_003 + k
            envs.append(RogueDeckEnv(config=config, seed=seed, abi=abi))
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"worker pid={os.getpid()} 建环境失败: {exc}"))
        conn.close()
        shm.close()
        return

    def publish(k: int, reward: int, done: bool) -> None:
        slot = (base_env + k) * stride
        abi.observe_into(envs[k].handle, stage)
        view[slot:slot + len(stage)] = stage
        view[slot + stride - 2] = reward
        view[slot + stride - 1] = 1 if done else 0

    try:
        for k in range(envs_per_worker):
            publish(k, abi.reward(envs[k].handle), abi.done(envs[k].handle))
        conn.send(("ready", os.getpid(), abi.observe_len()))

        while True:
            cmd = conn.recv()
            if cmd[0] == "step":
                for k, a in enumerate(cmd[1]):
                    env = envs[k]
                    if a < 0:
                        # "你自己挑"：取最后一个合法动作（通常是结束回合），
                        # 省掉调用方一次 action_count 往返。基准用它在无策略下跑满步数。
                        n = len(abi.actions(env.handle))
                        a = (n - 1) if n > 0 else 0
                    rc = abi.step(env.handle, a)
                    if rc != 0:
                        conn.send(("error", f"step({a}) -> {rc}: {abi.last_error()}"))
                        return
                    reward = abi.reward(env.handle)
                    done = abi.done(env.handle)
                    # auto_reset：一局结束就地重开。**不加这个，env 一生只走 6 步**，之后每次
                    # step 都是空转 —— 基准里它把吞吐压低了几十倍，训练里它会静默地只学到
                    # 头 6 步。返回的观察按 SB3 惯例是**重置后的初始观察**。
                    if done and auto_reset:
                        if abi.reset(env.handle) != 0:
                            conn.send(("error", f"reset 失败: {abi.last_error()}"))
                            return
                    publish(k, reward, done)
                conn.send(("ok",))
            elif cmd[0] == "close":
                conn.send(("ok",))
                return
            else:
                conn.send(("error", f"未知命令 {cmd[0]!r}"))
    except (EOFError, BrokenPipeError, OSError):
        pass  # 父进程先走了：安静退出，不要打一堆栈到 stderr
    finally:
        for env in envs:
            env.close()
        view.release()
        shm.close()
        conn.close()


class SubprocVecEnv:
    """N 个进程 × 每进程 M 个句柄 = N*M 个并行环境。观察经共享内存返回。"""

    def __init__(self, n_workers: int = 4, envs_per_worker: int = 4,
                 config: int = 0, base_seed: int = 1000, auto_reset: bool = True) -> None:
        if n_workers < 1 or envs_per_worker < 1:
            raise ValueError("n_workers 与 envs_per_worker 都必须 >= 1")
        self.n_workers = n_workers
        self.envs_per_worker = envs_per_worker
        self.n_envs = n_workers * envs_per_worker
        self.config = config
        self.base_seed = base_seed
        self.auto_reset = auto_reset
        self.epoch = 0
        self.observe_len: Optional[int] = None
        self.stride: Optional[int] = None
        self._ctx = mp.get_context("spawn")
        self._conns: List[Any] = []
        self._procs: List[Any] = []
        self._shm: Optional[shared_memory.SharedMemory] = None
        self._view: Optional[memoryview] = None
        self._initial_obs: List[List[int]] = []
        try:
            self._start()
        except BaseException:
            # 构造失败也必须收干净：共享内存留在那儿会变成孤儿映射（Windows 上还会
            # 让解释器退出时抛 BufferError，把真正的错误信息淹没掉）。
            self.close()
            raise

    # ---- 生命周期 ----

    def _start(self) -> None:
        # 先问一个观察长度：共享内存的尺寸依赖它。
        probe = EnvABI()
        self.observe_len = probe.observe_len()
        self.stride = _stride(self.observe_len)
        self._shm = shared_memory.SharedMemory(
            create=True, size=self.n_envs * self.stride * 4)  # int32
        self._view = memoryview(self._shm.buf).cast("i")

        self._conns, self._procs, self._initial_obs = [], [], []
        for w in range(self.n_workers):
            parent, child = self._ctx.Pipe()
            p = self._ctx.Process(
                target=_worker,
                args=(child, self._shm.name, w * self.envs_per_worker, self.config,
                      self.envs_per_worker, self.base_seed, self.epoch, self.auto_reset),
                daemon=True)
            p.start()
            child.close()  # 父进程必须关掉自己这一端，否则子进程退出时 recv 不报 EOF
            self._conns.append(parent)
            self._procs.append(p)

        for conn in self._conns:
            msg = conn.recv()
            if msg[0] == "error":
                self.close()
                raise RuntimeError(msg[1])
            if msg[2] != self.observe_len:
                self.close()
                raise RuntimeError(
                    f"某 worker 报出不同的 observe_len（{msg[2]} vs {self.observe_len}）"
                    f"—— 原生库不一致，先查构建产物")

        for i in range(self.n_envs):
            base = i * self.stride
            self._initial_obs.append(list(self._view[base:base + self.observe_len]))

    def reset(self, epoch: Optional[int] = None) -> List[List[int]]:
        """换一"轮"种子。句柄式 ABI 下这等于重建环境，所以是整进程重启 —— 明说比偷偷错好。"""
        self.close()
        self.epoch = (self.epoch + 1) if epoch is None else epoch
        self._start()
        return self._initial_obs

    def close(self) -> None:
        # 先发关闭请求，**再带超时地收**：如果某个 worker 已经死了或还没 ready，
        # 无超时的 recv() 会把整个 close() 挂死 —— 一个"关不掉的资源"比泄漏更难用。
        conns = list(getattr(self, "_conns", []))
        for conn in conns:
            try:
                conn.send(("close",))
            except (OSError, EOFError, ValueError):
                pass
        for conn in conns:
            try:
                if conn.poll(1.0):
                    conn.recv()
            except (OSError, EOFError):
                pass
            try:
                conn.close()
            except OSError:
                pass
        for p in getattr(self, "_procs", []):
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
        self._conns, self._procs = [], []
        if self._view is not None:
            try:
                self._view.release()
            except BufferError:
                pass  # 还有人持有切片；下面的 shm.close() 会在其释放后自然生效
            self._view = None
        if self._shm is not None:
            try:
                self._shm.close()
            except BufferError:
                pass
            try:
                self._shm.unlink()
            except (FileNotFoundError, OSError):
                pass
            self._shm = None

    # ---- 步进 ----

    def step(self, actions: Sequence[int]) -> Tuple[List[List[int]], List[int], List[bool]]:
        """返回 (obs, rewards, dones)。obs 是 Python 列表（兼容用）；
        要零拷贝请用 `step_raw()`。"""
        self._send_steps(actions)
        self._await()
        obs, rews, dones = [], [], []
        for i in range(self.n_envs):
            base = i * self.stride
            obs.append(list(self._view[base:base + self.observe_len]))
            rews.append(self._view[base + self.observe_len])
            dones.append(self._view[base + self.observe_len + 1] != 0)
        return obs, rews, dones

    def step_raw(self, actions: Sequence[int]) -> None:
        """只同步，不构造 Python 列表 —— 消费方直接读 `view`。

        训练循环里把观察拷成 Python 列表本身就是可观的开销（n_envs × 122 次取值）。
        要自己接张量/共享缓冲的调用方用这个，读 `self.view` 即可。
        """
        self._send_steps(actions)
        self._await()

    @property
    def view(self) -> memoryview:
        assert self._view is not None
        return self._view

    def _send_steps(self, actions: Sequence[int]) -> None:
        if len(actions) != self.n_envs:
            raise ValueError(f"需要 {self.n_envs} 个动作，收到 {len(actions)}")
        for w, conn in enumerate(self._conns):
            lo = w * self.envs_per_worker
            conn.send(("step", list(actions[lo:lo + self.envs_per_worker])))

    def _await(self) -> None:
        for conn in self._conns:
            msg = conn.recv()
            if msg[0] == "error":
                raise RuntimeError(msg[1])

    def __enter__(self) -> "SubprocVecEnv":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
