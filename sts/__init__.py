"""sts-tui —— 一个 Slay the Spire 式的 TUI 卡牌构筑 Roguelike 内核。

分层（硬规矩：core 不 import 任何渲染/输入相关的东西）：

    rng.py      多流确定性随机（seed + 计数器）
    events.py   事件总线（勾子 / 修饰器查询），带触发链深度保护
    state.py    数据模型（生物 / 战斗状态 / 快照哈希）
    db.py       内容数据库（卡牌 / 敌人 / 状态 / 遗物，全部来自 content/*.json）
    rules.py    修饰器管线（伤害 / 格挡）+ 状态行为注册
    actions.py  动作队列（命令模式，逻辑与表现解耦）
    effects.py  效果程序解释器（把卡面数据翻译成动作入队）
    combat.py   战斗回合状态机
    mapgen.py   地图生成（7x15 约束式 DAG，路径不交叉）
    run.py      单局流程（房间 / 奖励 / 商店 / 休息）
    tui.py      终端表现层（双宽字符对齐 + 战斗日志）
    sim.py      headless 自对弈与确定性校验
"""

__version__ = "0.1.0"
