using System.Runtime.InteropServices;
using System.Text;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// 交互式环境 ABI（冻结 v1，见 docs/spec/env-abi.md）—— 给 RL 训练用的逐决策接口。
///
/// 与 rd_oracle_run/_ex 的根本区别：那两个跑的是**固定脚本**（形状由 variant 选），本组导出让调用方
/// 「观察 -> 枚举合法动作 -> step -> 再看观察」。用固定脚本做不了 RL。
///
/// 三条硬约束（spec §2）决定了实现形状：
///   * **句柄式**：一个进程里并存 ≥16 个实例，所以每个实例的状态全在 <see cref="EnvInstance"/> 里，
///     没有一个"当前环境"的全局变量。句柄表本身是唯一的全局物（一个 Dictionary）。
///   * **不抛异常穿越边界**：一切错误变成返回码，人类可读原因进 rd_env_last_error_*。
///   * **拒绝时状态必须不变**：合法性在**动手之前**判（InteractiveCombat.CanPlay / CanUse 都是只读的），
///     所以"拒绝"这条路径根本不触碰 CombatState —— 这是结构上的保证，不是靠事后回滚。
///
/// 驱动引擎用的是 RogueDeck.Scenario 的 InteractiveCombat（逐步驱动真实回合：出牌、结束回合、
/// 敌人按意图行动、回到英雄下一回合），不是自己重新实现一套回合循环。
/// </summary>
public static partial class OracleExports
{
    // ── 观察向量布局（spec §4）────────────────────────────────────────────────────────────────────────
    internal const int ObsHeadLen = 12;
    internal const int ObsStatusLen = 5;
    internal const int ObsMaxEnemies = 4;
    internal const int ObsEnemyFields = 8;
    internal const int ObsMaxHand = 10;
    internal const int ObsHandFields = 4;
    internal const int ObsZoneLen = 5;
    internal const int ObsReservedLen = 8;

    internal const int OffEnemy = ObsHeadLen + ObsStatusLen;                                   // 17
    internal const int OffEnemyStatus = OffEnemy + ObsMaxEnemies * ObsEnemyFields;                // 49
    internal const int OffHand = OffEnemyStatus + ObsMaxEnemies * ObsStatusLen;              // 69
    internal const int OffZones = OffHand + ObsMaxHand * ObsHandFields;                           // 109
    internal const int OffReserved = OffZones + ObsZoneLen;                               // 114

    /// <summary>定长观察向量的长度：12 + 5 + 4*8 + 4*5 + 10*4 + 5 + 8 = 122。</summary>
    internal const int ObserveLen = OffReserved + ObsReservedLen;

    private static readonly StatusDefinitionId[] EnvStatusAxis =
    [
        StandardCombatIds.StrengthStatus,
        StandardCombatIds.VulnerableStatus,
        StandardCombatIds.WeakStatus,
        StandardCombatIds.DexterityStatus,
        StandardCombatIds.FrailStatus,
    ];

    // ── 每个句柄的全部状态（这里没有一个字段是共享的）────────────────────────────────────────────────
    private sealed class EnvInstance
    {
        public required InteractiveCombat Fight { get; init; }
        public required ScenarioBlueprint Blueprint { get; init; }
        public required int Config { get; init; }
        public required int Seed { get; init; }
        public int[] Obs { get; } = new int[ObserveLen];
        public List<(int Kind, int Arg0, int Arg1)> Actions { get; } = [];
        public int Reward;
    }

    private static readonly Dictionary<int, EnvInstance> EnvHandles = [];
    private static int _nextEnvHandle = 1;
    private static string _envError = string.Empty;
    private static List<(string Id, int Slot)>? _cardSlots;

    private static void EnvFail(string message)
    {
        _envError = message;
        _probeOk = 0;
    }

    // ── 内容：config 决定这一局长什么样 ───────────────────────────────────────────────────────────────
    //
    // 卡定义在所有 config 里都一样（这样 def_slot 的全局表是恒定的），config 只改英雄/敌人/牌组/起始状态。
    internal const string EnvCardStrike = "strike";     // 1 费 6 伤
    internal const string EnvCardDefend = "defend";     // 1 费 5 格挡
    internal const string EnvCardHeavy = "heavy";       // 2 费 12 伤
    internal const string EnvCardCleave = "cleave";     // 2 费，对所有敌人各 4 伤
    internal const string EnvCardJab = "jab";           // 0 费 3 伤
    internal const string EnvCardFocus = "focus";       // 1 费，自身 +2 力量
    internal const string EnvCardRecover = "recover";   // 1 费，自身回 4 血
    internal const string EnvCardBlast = "blast";       // 英雄动作：2 费 9 伤（不进牌组，是动作）
    internal const string EnvCardLocked = "locked";     // PlayCondition 恒假：**在动作表里但引擎会拒**
    internal const string EnvEnemyAction = "smash";

    /// <summary>
    /// config 清单（含义见 docs/spec/env-abi.md §10 与 native/env_check.py 的输出）：
    ///   0 duel       hero 30/30 + 1×12hp；牌组 5×strike(1费6伤)；敌人 5 伤
    ///   1 elite2     hero 50/50 + 2×14hp；牌组 5×strike + 3×defend(1费5格挡) + 1×heavy(2费12伤)；敌人 6 伤
    ///   2 statuses   hero 40/40 起手 Strength 2 + 2×16hp 起手 Vulnerable 2；牌组含 focus(1费+2力量)；敌人 7 伤
    ///   3 swarm4     hero 60/60 + 4×10hp；牌组含 cleave(2费，AllEnemiesOfSource 各 4 伤)；敌人 4 伤
    ///   4 action     hero 30/30 + 1×24hp；牌组 4×strike + 2×defend，另有**英雄动作** blast(2费9伤)
    ///   5 endurance  hero 80/80 + 3×20hp；10 张牌组（strike/defend/heavy/recover(1费回4血)/jab(0费3伤)）；敌人 5 伤
    ///   6 locked     hero 30/30 + 1×12hp；牌组 3×strike + 3×locked(PlayCondition 恒假) ——
    ///                实测 CanPlay **会**查 PlayCondition，所以 locked 根本进不了动作表（好事：
    ///                动作掩码是可靠的），这一格用来证明"掩码不会广告打不出去的牌"。
    ///   7 costfloor  hero 30/30 + 1×40hp；牌组 2×strike + 1×heavy(2费) + 3×jab(印刷 0 费)，
    ///                英雄起手戴「卡牌最低费用 = 1」的法令 ——
    ///                用来构造**在范围内但会被引擎拒绝**的动作：能量 0 时 jab 的印刷费用是 0，
    ///                我们的门控放行，而引擎按法令要 1 点能量 ⇒ 真·拒绝（这是 §8.3 第二类的样本）。
    /// </summary>
    internal const int ConfigCount = 8;

    internal const string EnvCardCostFloorDecree = "oracle.cost_floor";

    private static ScenarioBlueprint BuildEnvBlueprint(int config)
    {
        var fight = new ScenarioBlueprint { CardsDrawnPerTurn = 5 };

        CardBlueprint Card(string id, EffectProgram<CardPlayContext> program, int cost,
                           bool attack = false, bool isAction = false)
        {
            var card = new CardBlueprint(id) { Program = program, IsAction = isAction };
            card.Costs.Add(new ResourceCost(StandardCombatIds.EnergyResource, cost));
            if (attack)
                card.Tags.Add(StandardCombatIds.AttackCardTag);
            return card;
        }

        // ── 卡 ──
        fight.Cards.Add(Card(EnvCardStrike,
            Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 6)), 1, attack: true));
        fight.Cards.Add(Card(EnvCardDefend,
            Effects.Program(Effects.GainBlock(CombatantTargetSelectors.Source, 5)), 1));
        fight.Cards.Add(Card(EnvCardHeavy,
            Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 12)), 2, attack: true));
        fight.Cards.Add(Card(EnvCardCleave,
            new EffectProgram<CardPlayContext>(new ForEachTargetEffectNode<CardPlayContext>(
                CombatantTargetSelectors.AllEnemiesOfSource,
                new DealDamageNode<CardPlayContext>(
                    CombatantTargetSelectors.IterationTarget, Effects.Const(4)))),
            2, attack: true));
        fight.Cards.Add(Card(EnvCardJab,
            Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 3)), 0, attack: true));
        fight.Cards.Add(Card(EnvCardFocus,
            Effects.Program(
                Effects.ApplyStatus(CombatantTargetSelectors.Source, StandardCombatIds.StrengthStatus, 2)), 1));
        fight.Cards.Add(Card(EnvCardRecover,
            Effects.Program(Effects.Heal(CombatantTargetSelectors.Source, 4)), 1));
        // 英雄的"自身动作"：不进牌组、不用抽，靠 HeroBlueprint.Actions 使用（动作 kind 2）。
        fight.Cards.Add(Card(EnvCardBlast,
            Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 9)), 2,
            attack: true, isAction: true));
        // 只给 config 6 用：PlayCondition 恒假 ⇒ 打了也白打（引擎拒绝），用来测"范围内但会被拒"的路径。
        fight.Cards.Add(new CardBlueprint(EnvCardLocked)
        {
            Program = Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 99)),
            PlayCondition = new BoolConst(false),          // 见 Probes.cs 里的测试用布尔常量表达式
        }.Cost(StandardCombatIds.EnergyResource, 1));

        // 只给 config 7 用的法令：卡牌最低费用 1（能把 0 费卡变成 1 费，从而构造"被引擎拒绝"的动作）。
        var costFloor = new StatusBlueprint(EnvCardCostFloorDecree) { Polarity = StatusPolarity.Debuff };
        costFloor.CombatRules.Add(new CombatRuleSpec(CombatRule.MinimumCardCost, Amount: 1));
        fight.Statuses.Add(costFloor);

        // ── 敌人动作 ──
        var (enemyDamage, enemyHp, enemyCount, heroHp) = config switch
        {
            0 => (5, 12, 1, 30),      // duel：最小可收敛的一局
            1 => (6, 14, 2, 50),      // elite2：两个敌人 + 格挡/重击
            2 => (7, 16, 2, 40),      // statuses：双方带起始状态
            3 => (4, 10, 4, 60),      // swarm4：四个敌人（观察上限）
            4 => (6, 24, 1, 30),      // action：带英雄动作
            5 => (5, 20, 3, 80),      // endurance：长局，牌组更全
            6 => (5, 12, 1, 30),      // locked：牌组里混了 PlayCondition 恒假的牌
            7 => (1, 40, 1, 30),      // costfloor：长血敌人 + 「最低费用 1」法令，专供拒绝路径
            _ => throw new ArgumentOutOfRangeException(nameof(config), "unknown env config"),
        };

        fight.EnemyActions.Add(new EnemyActionBlueprint(EnvEnemyAction,
            new ActionIntent("Smash", IntentKind.Attack))
        {
            Program = new EffectProgram<EnemyActionContext>(
                new DealDamageNode<EnemyActionContext>(
                    CombatantTargetSelectors.EventTarget,
                    new ConstantExpression<EnemyActionContext>(enemyDamage))),
        });

        var hero = new HeroBlueprint("knight") { MaxHealth = heroHp };
        hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));

        switch (config)
        {
            case 0:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 5));
                break;
            case 1:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 5));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardDefend), Count: 3));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardHeavy), Count: 1));
                break;
            case 2:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 4));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardDefend), Count: 2));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardFocus), Count: 1));
                hero.StartingStatuses.Add(new StartingStatusSpec(StandardCombatIds.StrengthStatus, Stacks: 2));
                break;
            case 3:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 3));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardCleave), Count: 2));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardDefend), Count: 2));
                break;
            case 4:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 4));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardDefend), Count: 2));
                hero.Actions.Add(new CardDefinitionId(EnvCardBlast));
                break;
            case 6:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 3));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardLocked), Count: 3));
                break;
            case 7:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 2));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardHeavy), Count: 1));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardJab), Count: 3));
                hero.StartingStatuses.Add(new StartingStatusSpec(
                    new StatusDefinitionId(EnvCardCostFloorDecree)));
                break;
            default:
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardStrike), Count: 4));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardDefend), Count: 3));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardHeavy), Count: 1));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardRecover), Count: 1));
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(EnvCardJab), Count: 1));
                break;
        }
        fight.Hero = hero;

        for (var i = 0; i < enemyCount; i++)
        {
            var foe = new EnemyBlueprint("foe" + i) { MaxHealth = enemyHp };
            foe.Actions.Add(new EnemyActionDefinitionId(EnvEnemyAction));
            if (config == 2)
                foe.StartingStatuses.Add(new StartingStatusSpec(StandardCombatIds.VulnerableStatus, Stacks: 2));
            fight.Enemies.Add(foe);
        }

        return fight;
    }

    // 返回类型必须写成可空的 EnemyActionDefinitionId?，才与 InteractiveCombat 的
    // Func<CombatState, CombatantId, int, EnemyActionDefinitionId?> 精确匹配（否则 CS0407）。
    private static EnemyActionDefinitionId? EnemyIntent(CombatState state, CombatantId combatant, int round) =>
        new EnemyActionDefinitionId(EnvEnemyAction);

    // ── 生命周期 ─────────────────────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_env_create")]
    public static int EnvCreate(int config, int seed) => EnvCreateCore(config, seed);

    // 逻辑都在 *Core 里：UnmanagedCallersOnly 的方法不能被 C# 直接调用，而 rd_env_selfcheck 需要在
    // 进程内自己开句柄，所以导出层只做一层薄壳。
    private static int EnvCreateCore(int config, int seed)
    {
        _envError = string.Empty;
        try
        {
            if (config < 0 || config >= ConfigCount)
            {
                EnvFail($"config {config} out of range 0..{ConfigCount - 1}");
                return -1;
            }

            var blueprint = BuildEnvBlueprint(config);
            var compiled = blueprint.Compile();
            var fight = new InteractiveCombat(compiled, EnemyIntent,
                combatId: $"env{config}", randomSeed: seed, startOpeningTurn: true);

            var instance = new EnvInstance
            {
                Fight = fight,
                Blueprint = blueprint,
                Config = config,
                Seed = seed,
            };
            var handle = _nextEnvHandle++;
            EnvHandles[handle] = instance;
            EnvObserve(instance);
            return handle;
        }
        catch (Exception ex)
        {
            EnvFail($"create failed: {ex.GetType().Name}: {ex.Message}");
            return -2;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "rd_env_destroy")]
    public static void EnvDestroy(int handle)
    {
        if (EnvHandles.Remove(handle))
            return;
        EnvFail($"destroy: unknown handle {handle}");
    }

    /// <summary>把句柄复用到同一个 (config, seed) 的初始状态，返回 0。</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_reset")]
    public static int EnvReset(int handle)
    {
        _envError = string.Empty;
        if (!EnvHandles.TryGetValue(handle, out var old))
        {
            EnvFail($"reset: unknown handle {handle}");
            return -1;
        }
        try
        {
            var blueprint = BuildEnvBlueprint(old.Config);
            var fight = new InteractiveCombat(blueprint.Compile(), EnemyIntent,
                combatId: $"env{old.Config}", randomSeed: old.Seed, startOpeningTurn: true);
            var fresh = new EnvInstance
            {
                Fight = fight,
                Blueprint = blueprint,
                Config = old.Config,
                Seed = old.Seed,
            };
            EnvHandles[handle] = fresh;
            EnvObserve(fresh);
            return 0;
        }
        catch (Exception ex)
        {
            EnvFail($"reset failed: {ex.GetType().Name}: {ex.Message}");
            return -1;
        }
    }

    // ── 观察 ─────────────────────────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_env_observe_len")]
    public static int EnvObserveLen() => ObserveLen;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_observe")]
    public static int EnvObserveAt(int handle, int index)
    {
        if (!EnvHandles.TryGetValue(handle, out var env))
        {
            EnvFail($"observe: unknown handle {handle}");
            return int.MinValue;
        }
        return index >= 0 && index < ObserveLen ? env.Obs[index] : int.MinValue;
    }

    /// <summary>
    /// 把整条观察向量一次拷进调用方的缓冲区（**附加导出，不改 v1 契约**）。
    ///
    /// 为什么必须有它：`rd_env_observe` 是逐项取值，122 个整数就是 122 次跨 ABI 调用。实测这
    /// **40 µs/步**，占掉单步总成本的大头 —— RL 多开时它是第一瓶颈，而它跟游戏逻辑毫无关系。
    /// 这条导出把它变成一次 memcpy。用 `Marshal.Copy` 而不是指针，是为了不引入 unsafe 块。
    ///
    /// 返回写入的元素个数（即 <see cref="ObserveLen"/>）；-1 = 未知句柄；-2 = 容量不足（**不做部分写入**）。
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_observe_into")]
    public static int EnvObserveInto(int handle, IntPtr dst, int cap)
    {
        if (!EnvHandles.TryGetValue(handle, out var env))
        {
            EnvFail($"observe_into: unknown handle {handle}");
            return -1;
        }
        if (cap < ObserveLen)
        {
            EnvFail($"observe_into: capacity {cap} < {ObserveLen}");
            return -2;
        }
        Marshal.Copy(env.Obs, 0, dst, ObserveLen);
        return ObserveLen;
    }

    /// <summary>
    /// 终止判定 = 战斗已判出胜负 **或** 英雄已经倒下。后者必须单独算一档：英雄倒地而场上还有活着的
    /// 友方单位时 combat.Result 仍是 Ongoing，此时既没有可打的牌也没有"结束回合"（不是英雄的回合），
    /// 动作表会空掉 —— 对 RL 而言那已经是终局，不该让调用方在一个空动作表上打转。
    /// </summary>
    private static bool EnvIsDone(EnvInstance env) =>
        env.Fight.IsOver || !HeroAlive(env);

    private static bool HeroAlive(EnvInstance env) =>
        env.Fight.State.TryGetCombatant(env.Fight.HeroId, out var hero) && hero is { IsAlive: true };

    [UnmanagedCallersOnly(EntryPoint = "rd_env_done")]
    public static int EnvDone(int handle) =>
        EnvHandles.TryGetValue(handle, out var env) ? (EnvIsDone(env) ? 1 : 0) : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_result")]
    public static int EnvResult(int handle) =>
        EnvHandles.TryGetValue(handle, out var env) ? (int)env.Fight.Result : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_reward")]
    public static int EnvReward(int handle) =>
        EnvHandles.TryGetValue(handle, out var env) ? env.Reward : 0;

    // ── 动作 ─────────────────────────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_env_action_count")]
    public static int EnvActionCount(int handle) =>
        EnvHandles.TryGetValue(handle, out var env) ? env.Actions.Count : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_action_kind")]
    public static int EnvActionKind(int handle, int i) =>
        EnvHandles.TryGetValue(handle, out var env) && i >= 0 && i < env.Actions.Count
            ? env.Actions[i].Kind : int.MinValue;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_action_arg")]
    public static int EnvActionArg(int handle, int i, int which)
    {
        if (!EnvHandles.TryGetValue(handle, out var env) || i < 0 || i >= env.Actions.Count)
            return int.MinValue;
        var action = env.Actions[i];
        return which switch { 0 => action.Arg0, 1 => action.Arg1, _ => int.MinValue };
    }

    /// <summary>
    /// 施加一个动作。0 = 接受；-1 = 非法（**状态不变**）；-2 = 环境已结束；-3 = 其它（未知句柄等）。
    ///
    /// 合法性在**动手之前**判完：CanPlay / CanUse 都是只读的。真正兜底的是最后那道"观察有没有变"的
    /// 判据 —— 见下方注释：只要观察没变就返回 -1，变了就一定返回 0，所以「-1 ⇒ 零副作用」是构造上的
    /// 保证，而不是承诺。拒绝时 reward 一律清零（被拒的动作不是一步，不该带走奖励）。
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_step")]
    public static int EnvStep(int handle, int actionIndex) => EnvStepCore(handle, actionIndex);

    private static int Reject(EnvInstance env, string message, int code)
    {
        EnvFail(message);
        env.Reward = 0;
        return code;
    }

    private static int EnvStepCore(int handle, int actionIndex)
    {
        _envError = string.Empty;
        if (!EnvHandles.TryGetValue(handle, out var env))
        {
            EnvFail($"step: unknown handle {handle}");
            return -3;
        }
        if (EnvIsDone(env))
            return Reject(env, "step: the fight is over (or the hero is downed)", -2);
        if (actionIndex < 0 || actionIndex >= env.Actions.Count)
            return Reject(env, $"step: action index {actionIndex} out of range "
                             + $"0..{env.Actions.Count - 1}", -1);

        var (kind, arg0, arg1) = env.Actions[actionIndex];
        var hand = env.Fight.Hand;
        // arg1 是**观察里的敌人槽位下标**（稳定，敌人死了也不挪位），不是"存活敌人列表"的下标 ——
        // 第一版这里用了压缩过的存活列表，结果第一个敌人一死，之后所有攻击的目标都落到界外变成
        // null，卡片照样打出去但伤害谁也没挨着（表现为"卡在原地 200 步"）。
        var slots = EnemySlots(env);
        var before = SnapshotTotals(env);
        var beforeObs = (int[])env.Obs.Clone();

        try
        {
            switch (kind)
            {
                case 0:
                {
                    if (arg0 < 0 || arg0 >= hand.Count || !env.Fight.CanPlay(hand[arg0].Id))
                    {
                        return Reject(env, $"step: card at hand index {arg0} is not playable", -1);
                    }
                    // ⚠ InteractiveCombat.CanPlay 并**不看能量**：实测能量 0 时它仍返回 true，于是出牌
                    // 请求被引擎当"付不起"静默 no-op（牌还在手里、能量不变、没有伤害），而 env 会一直
                    // rc=0 —— 一局 200 步原地打转。所以自己补上能量这一刀，把这类牌从动作表里去掉。
                    if (DefinitionOf(env, hand[arg0].DefinitionId) is not { } cardDef ||
                        EnergyCostOf(cardDef) > env.Fight.HeroEnergy)
                    {
                        return Reject(env, $"step: card at hand index {arg0} costs more energy than the hero has", -1);
                    }
                    if (!TryTarget(slots, arg1, out var target))
                    {
                        return Reject(env, $"step: enemy slot {arg1} is not a living enemy", -1);
                    }
                    env.Fight.PlayCard(hand[arg0].Id, target);
                    break;
                }
                case 1:
                {
                    if (!env.Fight.IsHeroTurn)
                    {
                        return Reject(env, "step: it is not the hero's turn", -1);
                    }
                    env.Fight.EndTurn();
                    break;
                }
                case 2:
                {
                    var actions = env.Fight.Actions;
                    if (arg0 < 0 || arg0 >= actions.Count || !env.Fight.CanUse(actions[arg0]))
                    {
                        return Reject(env, $"step: hero action index {arg0} is not usable", -1);
                    }
                    if (DefinitionOf(env, actions[arg0]) is not { } actionDef ||
                        EnergyCostOf(actionDef) > env.Fight.HeroEnergy)
                    {
                        return Reject(env, $"step: hero action index {arg0} costs more energy than the hero has", -1);
                    }
                    if (!TryTarget(slots, arg1, out var target))
                    {
                        return Reject(env, $"step: enemy slot {arg1} is not a living enemy", -1);
                    }
                    env.Fight.UseAction(actions[arg0], target);
                    break;
                }
                default:
                    return Reject(env, $"step: action kind {kind} is reserved", -1);
            }
        }
        catch (Exception ex)
        {
            EnvFail($"step threw: {ex.GetType().Name}: {ex.Message}");
            return -3;
        }

        // ── 接受 / 拒绝的分界线：观察有没有真的动 ─────────────────────────────────────────────────
        // 不假定引擎"拒绝时一定报 problem"（实测它有时什么都不记），也不假定它一定不动——
        // 直接比观察。这样「返回 -1 ⇒ 状态不变」是**构造上的**保证，而不是靠事后回滚：
        // 只有观察确实没变才可能返回 -1，观察变了就一定返回 0。§8.3 的断言因此不可能被绕过。
        EnvObserve(env);
        var changed = false;
        for (var i = 0; i < ObserveLen && !changed; i++)
            changed = beforeObs[i] != env.Obs[i];
        if (!changed)
        {
            return Reject(env,
                "step: the engine no-opped this action (nothing in the observation changed)"
                + " | engine problems: " + LastStepProblems(env), -1);
        }

        env.Reward = kind == 1
            ? RewardFor(env, before, wastedEnergy: EnergyBefore(beforeObs))
            : RewardFor(env, before, wastedEnergy: 0);
        return 0;
    }

    /// <summary>步前的英雄能量（观察里的第 8 项），用来算"结束回合时没花掉的能量"。</summary>
    private static int EnergyBefore(int[] beforeObs) => beforeObs[8];

    // ── 卡定义句柄（spec §6）────────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_env_card_def_count")]
    public static int EnvCardDefCount()
    {
        EnsureCardSlots();
        return _cardSlots!.Count;
    }

    /// <summary>handle 自己的卡定义表里第 cardDefIndex 张 -> 全局稳定 slot；越界 -1。</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_card_def_slot")]
    public static int EnvCardDefSlot(int handle, int cardDefIndex)
    {
        if (!EnvHandles.TryGetValue(handle, out var env))
        {
            EnvFail($"card_def_slot: unknown handle {handle}");
            return -1;
        }
        EnsureCardSlots();
        var ids = SortedCardIds(env);
        if (cardDefIndex < 0 || cardDefIndex >= ids.Count)
            return -1;
        var found = _cardSlots!.FirstOrDefault(entry => entry.Id == ids[cardDefIndex]);
        return found.Id is null ? -1 : found.Slot;
    }

    private static string _envCardName = string.Empty;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_card_def_name_len")]
    public static int EnvCardDefNameLen(int slot)
    {
        EnsureCardSlots();
        _envCardName = slot >= 0 && slot < _cardSlots!.Count ? _cardSlots[slot].Id : string.Empty;
        return _envCardName.Length;
    }

    /// <summary>读上一次 rd_env_card_def_name_len(slot) 取到的那张卡的名字（沿用同一套缓冲约定）。</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_card_def_name_char")]
    public static int EnvCardDefNameChar(int i) =>
        i >= 0 && i < _envCardName.Length ? _envCardName[i] : -1;

    // ── 诊断 ─────────────────────────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_env_last_error_len")]
    public static int EnvLastErrorLen() => _envError.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_env_last_error_char")]
    public static int EnvLastErrorChar(int i) => i >= 0 && i < _envError.Length ? _envError[i] : -1;

    /// <summary>
    /// 自检：同 (config, seed) 开两个**互不相干**的句柄，用同一条确定性策略各走 steps 步，
    /// 逐项比较每一步之后的观察向量。一致返回 1，不一致返回 0，出错返回负值。
    /// 这是 spec §2.4「同 (config, seed) + 同动作序列 ⇒ 观察流逐字节相同」的可执行版本。
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_env_selfcheck")]
    public static int EnvSelfcheck(int config, int seed, int steps)
    {
        _envError = string.Empty;
        var a = EnvCreateCore(config, seed);
        var b = EnvCreateCore(config, seed);
        if (a < 0 || b < 0)
            return -1;
        try
        {
            for (var step = 0; step < steps; step++)
            {
                if (EnvIsDone(EnvHandles[a]) || EnvIsDone(EnvHandles[b]))
                    return 1;                       // 两边都结束了：到这里的观察已经比过
                var countA = EnvHandles[a].Actions.Count;
                var countB = EnvHandles[b].Actions.Count;
                if (countA != countB)
                    return 0;                       // 动作表都不一样了
                for (var i = 0; i < countA; i++)
                {
                    var (ka, a0, a1) = EnvHandles[a].Actions[i];
                    var (kb, b0, b1) = EnvHandles[b].Actions[i];
                    if (ka != kb || a0 != b0 || a1 != b1)
                        return 0;
                }
                // 确定性策略：总是取第 0 个动作（没有可打的牌时它自然就是"结束回合"）。
                var pick = DeterministicPick(EnvHandles[a].Actions);
                var ra = EnvStepCore(a, pick);
                var rb = EnvStepCore(b, pick);
                if (ra != rb)
                    return 0;
                for (var i = 0; i < ObserveLen; i++)
                    if (EnvHandles[a].Obs[i] != EnvHandles[b].Obs[i])
                        return 0;
                if (EnvHandles[a].Reward != EnvHandles[b].Reward)
                    return 0;
            }
            return 1;
        }
        catch (Exception ex)
        {
            EnvFail($"selfcheck threw: {ex.GetType().Name}: {ex.Message}");
            return -1;
        }
        finally
        {
            EnvHandles.Remove(a);
            EnvHandles.Remove(b);
        }
    }

    /// <summary>确定性选策：优先打第一张手牌，否则结束回合，否则用英雄动作。</summary>
    internal static int DeterministicPick(List<(int Kind, int Arg0, int Arg1)> actions)
    {
        for (var i = 0; i < actions.Count; i++)
            if (actions[i].Kind == 0)
                return i;
        for (var i = 0; i < actions.Count; i++)
            if (actions[i].Kind == 1)
                return i;
        return actions.Count > 0 ? 0 : -1;
    }

    // ── 内部：观察编码 ────────────────────────────────────────────────────────────────────────────────

    private static void EnvObserve(EnvInstance env)
    {
        var obs = env.Obs;
        Array.Fill(obs, -1);
        for (var i = 0; i < ObsReservedLen; i++)
            obs[OffReserved + i] = 0;             // 保留区按 spec 置 0

        var fight = env.Fight;
        var state = fight.State;
        var hero = state.GetCombatant(fight.HeroId);

        obs[0] = state.CurrentRound;
        obs[1] = state.CurrentTurn;
        obs[2] = (int)state.TurnPhase;
        obs[3] = (int)state.Result;
        obs[4] = hero.Health.Current;
        obs[5] = hero.Health.Max;
        obs[6] = PoolOf(hero, StandardCombatIds.BlockDefensivePool);
        obs[7] = PoolOf(hero, WardPool);
        obs[8] = fight.HeroEnergy;
        obs[9] = fight.HeroEnergyMax;

        var hand = fight.Hand;
        var allEnemies = state.Combatants
            .Where(combatant => combatant.TeamId == StandardCombatIds.EnemyTeam)
            .Take(ObsMaxEnemies)
            .ToList();

        obs[10] = hand.Count;
        obs[11] = allEnemies.Count;

        for (var axis = 0; axis < ObsStatusLen; axis++)
            obs[ObsHeadLen + axis] = StacksOf(hero, EnvStatusAxis[axis]);

        // 意图伤害：一次 Fork 就能拿到"现在结束回合会挨多少"，按敌人分摊到各自的槽位。
        Dictionary<string, int> intentDamage = [];
        var foresight = fight.Foresee();
        if (foresight is not null)
            foreach (var blow in foresight.Blows)
                intentDamage[blow.Enemy.value] = blow.Amount;

        for (var e = 0; e < ObsMaxEnemies; e++)
        {
            var at = OffEnemy + e * ObsEnemyFields;
            var statusAt = OffEnemyStatus + e * ObsStatusLen;
            if (e >= allEnemies.Count)
                continue;                            // 整块保持 -1（未占用）

            var foe = allEnemies[e];
            var intent = fight.UpcomingIntentFor(foe.Id);
            obs[at + 0] = foe.IsAlive ? 1 : 0;
            obs[at + 1] = foe.Health.Current;
            obs[at + 2] = foe.Health.Max;
            obs[at + 3] = PoolOf(foe, StandardCombatIds.BlockDefensivePool);
            obs[at + 4] = PoolOf(foe, WardPool);
            obs[at + 5] = intent is null ? -1 : (int)intent.Kind;
            obs[at + 6] = intentDamage.TryGetValue(foe.Id.value, out var amount) ? amount : -1;
            obs[at + 7] = 0;
            for (var axis = 0; axis < ObsStatusLen; axis++)
            {
                var stacks = StacksOf(foe, EnvStatusAxis[axis]);
                obs[statusAt + axis] = stacks;
                if (stacks != 0)
                    obs[at + 7]++;
            }
        }

        for (var c = 0; c < ObsMaxHand; c++)
        {
            var at = OffHand + c * ObsHandFields;
            if (c >= hand.Count)
                continue;                            // 整块保持 -1（没有这张牌）
            var definition = state.DefinitionRegistry is { } registry
                             && registry.CardDefinitions.TryGetValue(hand[c].DefinitionId, out var found)
                ? found : null;
            obs[at + 0] = 1;
            obs[at + 1] = definition is null ? 0 : EnergyCostOf(definition);
            obs[at + 2] = CardSlotOf(hand[c].DefinitionId.value);
            obs[at + 3] = 0;                        // v1 没有升级机制，保留字段
        }

        var zones = state.GetCardZones(fight.HeroId);
        obs[OffZones + 0] = zones.DrawPile.Count;
        obs[OffZones + 1] = zones.Hand.Count;
        obs[OffZones + 2] = zones.DiscardPile.Count;
        obs[OffZones + 3] = zones.ExhaustPile.Count;
        obs[OffZones + 4] = zones.Queue.Count;

        EnvRebuildActions(env, allEnemies);
    }

    private static void EnvRebuildActions(EnvInstance env, List<CombatantState> allEnemies)
    {
        env.Actions.Clear();
        if (EnvIsDone(env))
            return;

        var living = allEnemies.Where(foe => foe.IsAlive).ToList();
        var hand = env.Fight.Hand;
        var energy = env.Fight.HeroEnergy;
        for (var i = 0; i < hand.Count; i++)
        {
            if (!env.Fight.CanPlay(hand[i].Id))
                continue;
            if (DefinitionOf(env, hand[i].DefinitionId) is not { } definition)
                continue;
            if (EnergyCostOf(definition) > energy)
                continue;                           // CanPlay 不看能量，非法动作不该进动作表
            var isAttack = definition.Tags.Contains(StandardCombatIds.AttackCardTag);
            if (isAttack && living.Count > 0)
            {
                // 攻击牌：每个存活敌人一个动作（arg1 = 该敌人在观察里的槽位下标）。
                for (var e = 0; e < allEnemies.Count; e++)
                    if (allEnemies[e].IsAlive)
                        env.Actions.Add((0, i, e));
            }
            else
            {
                env.Actions.Add((0, i, -1));
            }
        }

        if (env.Fight.IsHeroTurn)
            env.Actions.Add((1, -1, -1));

        var actions = env.Fight.Actions;
        for (var a = 0; a < actions.Count; a++)
        {
            if (!env.Fight.CanUse(actions[a]))
                continue;
            // 与手牌同理：CanUse 也不看能量，自己补这一刀（动作表不该出现付不起的动作）。
            if (DefinitionOf(env, actions[a]) is { } actionDef && EnergyCostOf(actionDef) > energy)
                continue;
            if (living.Count > 0)
            {
                for (var e = 0; e < allEnemies.Count; e++)
                    if (allEnemies[e].IsAlive)
                        env.Actions.Add((2, a, e));
            }
            else
            {
                env.Actions.Add((2, a, -1));
            }
        }
    }

    /// <summary>观察里的敌人槽位（turn order，最多 MaxEnemies 个，死后不挪位）。</summary>
    private static List<CombatantState> EnemySlots(EnvInstance env) =>
        env.Fight.State.Combatants
            .Where(combatant => combatant.TeamId == StandardCombatIds.EnemyTeam)
            .Take(ObsMaxEnemies)
            .ToList();

    /// <summary>把槽位下标翻成目标：-1 = 无目标；越界/已死返回 false（调用方据此拒绝）。</summary>
    private static bool TryTarget(List<CombatantState> slots, int slot, out CombatantId? target)
    {
        if (slot == -1)
        {
            target = null;
            return true;
        }
        if (slot < 0 || slot >= slots.Count || !slots[slot].IsAlive)
        {
            target = null;
            return false;
        }
        target = slots[slot].Id;
        return true;
    }

    // ── 内部：奖励（spec §7，单位 1/1000）────────────────────────────────────────────────────────────

    private readonly record struct Totals(int EnemyHp, int HeroHp);

    private static Totals SnapshotTotals(EnvInstance env)
    {
        var enemyHp = env.Fight.State.Combatants
            .Where(c => c.TeamId == StandardCombatIds.EnemyTeam)
            .Sum(c => c.Health.Current);
        return new Totals(enemyHp, env.Fight.State.GetCombatant(env.Fight.HeroId).Health.Current);
    }

    private static int RewardFor(EnvInstance env, Totals before, int wastedEnergy)
    {
        var after = SnapshotTotals(env);
        var enemyLoss = before.EnemyHp - after.EnemyHp;
        var heroLoss = before.HeroHp - after.HeroHp;
        return 1000 * enemyLoss - 1000 * heroLoss - 10 * wastedEnergy;
    }

    // ── 内部：卡定义 slot 表（全局、稳定、按 id 排序）────────────────────────────────────────────────

    private static void EnsureCardSlots()
    {
        if (_cardSlots is not null)
            return;
        var builder = new CombatDefinitionRegistryBuilder();
        new StandardCombatPackage(5).RegisterDefinitions(builder);
        var probe = BuildEnvBlueprint(0);
        foreach (var card in probe.Cards)
            builder.RegisterCard(card.Compile());
        var registry = builder.Build();
        _cardSlots = registry.CardDefinitions.Keys
            .Select(id => id.value)
            .OrderBy(id => id, StringComparer.Ordinal)
            .Select((id, slot) => (Id: id, Slot: slot))
            .ToList();
    }

    private static int CardSlotOf(string definitionId)
    {
        EnsureCardSlots();
        foreach (var entry in _cardSlots!)
            if (entry.Id == definitionId)
                return entry.Slot;
        return -1;
    }

    private static List<string> SortedCardIds(EnvInstance env) =>
        (env.Fight.State.DefinitionRegistry?.CardDefinitions.Keys ?? [])
            .Select(id => id.value)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToList();

    private static int EnergyCostOf(CardDefinition definition)
    {
        foreach (var cost in definition.Costs)
            if (cost.ResourceId == StandardCombatIds.EnergyResource)
                return cost.Amount;
        return 0;
    }

    private static string LastStepProblems(EnvInstance env)
    {
        var steps = env.Fight.Steps;
        return steps.Count == 0 ? "(no step recorded)" : string.Join(" | ", steps[steps.Count - 1].Problems);
    }

    private static CardDefinition? DefinitionOf(EnvInstance env, CardDefinitionId id) =>
        env.Fight.State.DefinitionRegistry is { } registry
        && registry.CardDefinitions.TryGetValue(id, out var found)
            ? found
            : null;
}
