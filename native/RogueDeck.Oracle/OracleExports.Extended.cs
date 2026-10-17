using System.Runtime.InteropServices;
using System.Text;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// The WIDE scenario runner: same authoring path as <c>rd_oracle_run</c>, but with the knobs the spec's
/// acceptance vectors actually need — starting status stacks on both sides, a damage kind, a multi-hit card,
/// a card that grants Block or a custom defensive pool, queue-on-play, and more than one enemy.
///
/// The point of this export is that a spec vector can be stated as one row of numbers and answered by the
/// real engine, instead of being taken on faith.
///
/// <c>rd_oracle_run</c> is deliberately left untouched: the 128 cases of corpus/golden_v1.jsonl are pinned to
/// it, so widening the ABI had to mean adding a second entry point rather than editing the first.
/// </summary>
public static partial class OracleExports
{
    private static readonly DefensivePoolId WardPool = new("oracle.ward");

    // ── extended observables ────────────────────────────────────────────────────────────────────────────
    private static int _heroBlock, _enemyBlock, _heroWard, _enemyWard;
    private static int _energy, _energyMax, _handCount, _drawCount, _discardCount, _exhaustCount, _queueCount;
    private static int _enemyCount, _phase, _result, _played;
    private static readonly int[] EnemyHpAt = new int[16];
    private static readonly int[] EnemyBlockAt = new int[16];
    private static readonly int[] HeroStacks = new int[5];
    private static readonly int[] EnemyStacks = new int[5];
    private static string _detail = string.Empty;

    private static readonly StatusDefinitionId[] StatusAxis =
    [
        StandardCombatIds.StrengthStatus,     // 0
        StandardCombatIds.VulnerableStatus,   // 1
        StandardCombatIds.WeakStatus,         // 2
        StandardCombatIds.DexterityStatus,    // 3
        StandardCombatIds.FrailStatus,        // 4
    ];

    /// <summary>
    /// Authors one fight with a parameterised card and enemy set, runs the script selected by
    /// <paramref name="variant"/>, and stashes the observables.
    ///
    /// cardKind: 0 = Direct, 1 = DamageOverTime, 2 = Direct + IgnoresBlock, 3 = DamageOverTime + IgnoresBlock.
    /// cardBlockTarget / cardDamageTarget: 0 = the hero (the card's source), 1 = the event target (an enemy).
    /// cardHits: the card issues this many separate damage nodes, so each hit goes through the modifier
    /// pipeline on its own (that is what "a 3-hit card" means to the engine).
    /// variant: which script to drive — see <see cref="BuildScriptEx"/>.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_run_ex")]
    public static int RunEx(
        int heroHp,
        int cardDamage, int cardHits, int cardDamageTarget, int cardKind,
        int cardBlock, int cardBlockTarget, int cardWard,
        int cardCost, int queueOnPlay,
        int enemyHp, int enemyDamage, int enemyCount,
        int heroStrength, int heroVulnerable, int heroWeak, int heroDexterity, int heroFrail,
        int enemyStrength, int enemyVulnerable, int enemyWeak, int enemyDexterity, int enemyFrail,
        int drawPerTurn, int deckSize,
        int seed, int variant)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _played = -1;
        try
        {
            if (enemyCount < 1 || enemyCount > 16)
                throw new ArgumentOutOfRangeException(nameof(enemyCount), "enemyCount must be 1..16.");
            if (cardHits < 0 || cardHits > 64)
                throw new ArgumentOutOfRangeException(nameof(cardHits), "cardHits must be 0..64.");
            if (deckSize < 1 || deckSize > 64)
                throw new ArgumentOutOfRangeException(nameof(deckSize), "deckSize must be 1..64.");

            var fight = new ScenarioBlueprint { CardsDrawnPerTurn = Math.Max(1, drawPerTurn) };

            // The custom pool is always registered, so a card may move it whether or not this case uses it.
            // AbsorbPriority 10 puts it strictly AFTER Block (0), which is what spec §7#7 turns on.
            fight.DefensivePools.Add(new DefensivePoolDefinition(WardPool, AbsorbPriority: 10));

            var program = BuildCardProgram(cardDamage, cardHits, cardDamageTarget, cardKind,
                                           cardBlock, cardBlockTarget, cardWard);
            var card = new CardBlueprint(CardId) { Program = program, QueueOnPlay = queueOnPlay != 0 }
                .Cost(StandardCombatIds.EnergyResource, cardCost);
            fight.Cards.Add(card);

            fight.EnemyActions.Add(new EnemyActionBlueprint("smash",
                new ActionIntent("Smash", IntentKind.Attack))
            {
                Program = new EffectProgram<EnemyActionContext>(
                    new DealDamageNode<EnemyActionContext>(
                        CombatantTargetSelectors.EventTarget,
                        new ConstantExpression<EnemyActionContext>(enemyDamage))),
            });

            fight.Hero = new HeroBlueprint(HeroId) { MaxHealth = Math.Max(1, heroHp) };
            fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(CardId), Count: deckSize));
            fight.Hero.Resources.Add(
                new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));
            AddStatuses(fight.Hero, heroStrength, heroVulnerable, heroWeak, heroDexterity, heroFrail);

            for (var i = 0; i < enemyCount; i++)
            {
                var foe = new EnemyBlueprint(EnemyId(i)) { MaxHealth = Math.Max(1, enemyHp) };
                foe.Actions.Add(new EnemyActionDefinitionId("smash"));
                AddStatuses(foe, enemyStrength, enemyVulnerable, enemyWeak, enemyDexterity, enemyFrail);
                fight.Enemies.Add(foe);
            }

            var report = new ScenarioRunner()
                .Run(new Playthrough(fight, BuildScriptEx(variant), combatId: "oracle_ex", randomSeed: seed));

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    internal const string CardId = "strike";
    internal const string HeroId = "knight";

    internal static string EnemyId(int index) => "foe" + index;

    private static EffectProgram<CardPlayContext> BuildCardProgram(
        int cardDamage, int cardHits, int cardDamageTarget, int cardKind,
        int cardBlock, int cardBlockTarget, int cardWard)
    {
        // Pool/Block moves come FIRST in the program, and that ordering is load-bearing: a Sequence's
        // children each ENQUEUE their request, and the queue then drains in order, so Block granted by node 1
        // is standing when node 3's damage resolves. That is how "the target already had 5 Block" is staged
        // without a second turn (the cited C# test seeds the pool directly with AddDefensivePool instead).
        var nodes = new List<IEffectNode<CardPlayContext>>();

        if (cardWard != 0)
            nodes.Add(new ModifyDefensivePoolNode<CardPlayContext>(
                CombatantTargetSelectors.Source, WardPool, Effects.Const(cardWard)));

        if (cardBlock != 0)
            nodes.Add(new GainBlockNode<CardPlayContext>(
                TargetFor(cardBlockTarget), Effects.Const(cardBlock)));

        if (cardHits > 0)
        {
            var ignoresBlock = cardKind is 2 or 3;
            var kind = cardKind is 1 or 3 ? DamageKind.DamageOverTime : DamageKind.Direct;
            var target = TargetFor(cardDamageTarget);
            for (var hit = 0; hit < cardHits; hit++)
                nodes.Add(new DealDamageNode<CardPlayContext>(
                    target, Effects.Const(cardDamage),
                    ignoresBlock: ignoresBlock, kind: kind));
        }

        IEffectNode<CardPlayContext> root = nodes.Count switch
        {
            0 => new NoOpEffectNode<CardPlayContext>(),
            1 => nodes[0],
            _ => new SequenceEffectNode<CardPlayContext>(nodes),
        };
        return new EffectProgram<CardPlayContext>(root);
    }

    private static ICombatantTargetSelector TargetFor(int which) =>
        which == 0 ? CombatantTargetSelectors.Source : CombatantTargetSelectors.EventTarget;

    private static void AddStatuses(
        CombatantBlueprint combatant,
        int strength, int vulnerable, int weak, int dexterity, int frail)
    {
        Add(StandardCombatIds.StrengthStatus, strength);
        Add(StandardCombatIds.VulnerableStatus, vulnerable);
        Add(StandardCombatIds.WeakStatus, weak);
        Add(StandardCombatIds.DexterityStatus, dexterity);
        Add(StandardCombatIds.FrailStatus, frail);

        void Add(StatusDefinitionId id, int stacks)
        {
            if (stacks > 0)
                combatant.StartingStatuses.Add(new StartingStatusSpec(id, Stacks: stacks));
        }
    }

    private static IReadOnlyList<ScenarioStep> BuildScriptEx(int variant)
    {
        var script = new ScenarioScript();
        switch (variant)
        {
            case 0:                                     // play once, no turn boundary
                script.HeroPlays(CardId, EnemyId(0));
                break;
            case 1:                                     // play, then the enemy swings back
                script.HeroPlays(CardId, EnemyId(0)).HeroEndsTurn().EnemyActs(EnemyId(0), "smash", HeroId);
                break;
            case 2:                                     // play, end turn, wrap the round
                script.HeroPlays(CardId, EnemyId(0)).HeroEndsTurn().NextRound();
                break;
            case 3:                                     // play twice (energy + deck cycling)
                script.HeroPlays(CardId, EnemyId(0)).HeroPlays(CardId, EnemyId(0)).HeroEndsTurn();
                break;
            case 4:                                     // play, wrap a whole round, play again
                script.HeroPlays(CardId, EnemyId(0)).HeroEndsTurn().NextRound().HeroPlays(CardId, EnemyId(0));
                break;
            case 5:                                     // control: never play
                script.HeroEndsTurn();
                break;
            case 6:                                     // play then end the turn ONCE - the queue-resolution window
                script.HeroPlays(CardId, EnemyId(0)).HeroEndsTurn();
                break;
            case 7:                                     // turn/round bookkeeping only
                script.HeroEndsTurn().NextRound().HeroEndsTurn();
                break;
            default:
                script.HeroPlays(CardId, EnemyId(0));
                break;
        }
        return script.Build();
    }

    // ── capture ─────────────────────────────────────────────────────────────────────────────────────────

    private static void Capture(ScenarioReport report)
    {
        var problems = report.Steps.SelectMany(step => step.Problems).ToList();
        CaptureState(report.FinalState, problems, report.Steps.Count,
                     report.Steps.Any(step => step.Step is HeroPlaysCard));
    }

    /// <summary>
    /// The single observation point: everything the exports hand back is filled from here, so a scenario run
    /// and a probe that drives the engine directly produce the same shape of answer.
    /// </summary>
    internal static void CaptureState(
        CombatState final, IReadOnlyList<string> problems, int stepCount, bool playedSomething)
    {
        var snapshot = final.CreateSnapshot();

        _probeOk = 0;
        _hash = CombatStateHasher.ComputeHash(snapshot);
        StoreHashInput(snapshot);
        _steps = stepCount;
        _problems = problems.Count > 0 ? 1 : 0;
        _heroHp = final.GetCombatant(new CombatantId(HeroId)).Health.Current;
        _round = final.CurrentRound;
        _turn = final.CurrentTurn;
        _randomStep = final.RandomStep;
        _pending = final.PendingEffectCount;
        _logCount = final.CombatLog.Count;
        _phase = (int)final.TurnPhase;
        _result = (int)final.Result;

        var hero = final.GetCombatant(new CombatantId(HeroId));
        ReplayDetail(final, problems, hero, playedSomething);
    }

    private static void ReplayDetail(
        CombatState final, IReadOnlyList<string> problems, CombatantState hero, bool playedSomething)
    {
        _heroBlock = PoolOf(hero, StandardCombatIds.BlockDefensivePool);
        _heroWard = PoolOf(hero, WardPool);
        var energy = hero.Resources.TryGetValue(StandardCombatIds.EnergyResource, out var pool) ? pool : null;
        _energy = energy?.Current ?? -1;
        _energyMax = energy?.Max ?? -1;

        var zones = final.GetCardZones(new CombatantId(HeroId));
        _handCount = zones.Hand.Count;
        _drawCount = zones.DrawPile.Count;
        _discardCount = zones.DiscardPile.Count;
        _exhaustCount = zones.ExhaustPile.Count;
        _queueCount = zones.Queue.Count;

        var detail = new StringBuilder();
        detail.Append("active=").Append(final.ActiveCombatantId?.value ?? "");
        detail.Append(";result=").Append(final.Result);
        detail.Append(";phase=").Append(final.TurnPhase);
        detail.Append(";hand=").Append(Ids(zones.Hand));
        detail.Append(";draw=").Append(Ids(zones.DrawPile));
        detail.Append(";disc=").Append(Ids(zones.DiscardPile));
        detail.Append(";queue=").Append(Ids(zones.Queue));
        detail.Append(";heroStatuses=").Append(Statuses(hero));
        detail.Append(";problems=").Append(string.Join(" | ", problems));

        for (var axis = 0; axis < StatusAxis.Length; axis++)
        {
            HeroStacks[axis] = StacksOf(hero, StatusAxis[axis]);
            EnemyStacks[axis] = 0;
        }

        _enemyCount = 0;
        var foes = new StringBuilder();
        foreach (var combatant in final.Combatants)
        {
            if (combatant.TeamId != StandardCombatIds.EnemyTeam)
                continue;
            if (_enemyCount >= EnemyHpAt.Length)
                break;

            EnemyHpAt[_enemyCount] = combatant.Health.Current;
            EnemyBlockAt[_enemyCount] = PoolOf(combatant, StandardCombatIds.BlockDefensivePool);
            if (_enemyCount == 0)
            {
                _enemyHp = combatant.Health.Current;
                _enemyBlock = EnemyBlockAt[0];
                _enemyWard = PoolOf(combatant, WardPool);
                for (var axis = 0; axis < StatusAxis.Length; axis++)
                    EnemyStacks[axis] = StacksOf(combatant, StatusAxis[axis]);
            }
            if (_enemyCount > 0)
                foes.Append(',');
            foes.Append(combatant.Id.value).Append(':')
                .Append(combatant.Health.Current).Append('/').Append(EnemyBlockAt[_enemyCount]);
            _enemyCount++;
        }
        detail.Append(";enemies=").Append(foes);

        // Player-team members other than the hero (a fielded ally). The martyr vector needs to see the
        // protector's HP, and it is neither the hero nor an enemy.
        var party = new StringBuilder();
        foreach (var combatant in final.Combatants)
        {
            if (combatant.TeamId != StandardCombatIds.PlayerTeam || combatant.Id.value == HeroId)
                continue;
            if (party.Length > 0)
                party.Append(',');
            party.Append(combatant.Id.value).Append(':').Append(combatant.Health.Current)
                .Append('/').Append(PoolOf(combatant, StandardCombatIds.BlockDefensivePool));
        }
        detail.Append(";party=").Append(party);

        // The log goes LAST and uses '\n' as its entry separator because the messages contain spaces, colons
        // and apostrophes. The type alone says an effect happened; the message says WHICH one (the amount, the
        // pool id, the combatant), which is what makes the ordering vectors decidable.
        detail.Append(";log=");
        for (var i = 0; i < final.CombatLog.Count; i++)
        {
            if (i > 0)
                detail.Append('\n');
            detail.Append(final.CombatLog[i].Type).Append('@').Append(final.CombatLog[i].Message);
        }

        // -1 = the script never played a card; 0 = the runner reported the play was refused; 1 = it landed.
        _played = playedSomething
            ? (problems.Any(text => text.Contains("was not played")) ? 0 : 1)
            : -1;

        _detail = detail.ToString();
    }

    private static string Ids(IReadOnlyList<CardInstance> cards) =>
        string.Join(",", cards.Select(card => card.DefinitionId.value));

    private static string Statuses(CombatantState combatant) =>
        string.Join(",", combatant.Statuses.Select(s =>
            s.DefinitionId.value + ":" + s.Stacks + "/" + s.DurationTurns + "/" + s.Charges));

    private static int PoolOf(CombatantState combatant, DefensivePoolId id) =>
        combatant.DefensivePools.TryGetValue(id, out var pool) ? pool.Current : 0;

    private static int StacksOf(CombatantState combatant, StatusDefinitionId id) =>
        combatant.Statuses.Where(status => status.DefinitionId == id).Sum(status => status.Stacks);

    // ── extended observable exports ─────────────────────────────────────────────────────────────────────

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hero_block")] public static int HeroBlock() => _heroBlock;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_block")] public static int EnemyBlock() => _enemyBlock;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hero_ward")] public static int HeroWard() => _heroWard;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_ward")] public static int EnemyWard() => _enemyWard;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_energy")] public static int Energy() => _energy;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_energy_max")] public static int EnergyMax() => _energyMax;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hand_count")] public static int HandCount() => _handCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_draw_count")] public static int DrawCount() => _drawCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_discard_count")] public static int DiscardCount() => _discardCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_exhaust_count")] public static int ExhaustCount() => _exhaustCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_queue_count")] public static int QueueCount() => _queueCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_count")] public static int EnemyCount() => _enemyCount;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_phase")] public static int Phase() => _phase;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_result")] public static int Result() => _result;
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_played")] public static int Played() => _played;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_hp_at")]
    public static int EnemyHpAt_(int index) =>
        index >= 0 && index < _enemyCount ? EnemyHpAt[index] : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_block_at")]
    public static int EnemyBlockAt_(int index) =>
        index >= 0 && index < _enemyCount ? EnemyBlockAt[index] : -1;

    /// <summary>Stacks of the standard status on the HERO. axis: 0 strength, 1 vulnerable, 2 weak, 3 dexterity, 4 frail.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hero_stacks")]
    public static int HeroStacks_(int axis) =>
        axis >= 0 && axis < HeroStacks.Length ? HeroStacks[axis] : -1;

    /// <summary>Same, on the first enemy.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_stacks")]
    public static int EnemyStacks_(int axis) =>
        axis >= 0 && axis < EnemyStacks.Length ? EnemyStacks[axis] : -1;

    /// <summary>
    /// The string-y half of the observation: active combatant, hand/draw/discard/queue card ids, the combat
    /// log's entry types in order, the hero's statuses, the enemy roster, and every problem the runner
    /// reported. One buffer, read character by character like the hash.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_text_len")]
    public static int TextLen() => _detail.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_text_char")]
    public static int TextChar(int i) => i >= 0 && i < _detail.Length ? _detail[i] : -1;
}
