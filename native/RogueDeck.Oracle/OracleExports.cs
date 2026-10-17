using System.Runtime.InteropServices;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// Golden-model oracle: build a combat from the authoring DSL, run a scripted sequence of
/// commands on the real engine, and hand back the state hash plus a few observables.
///
/// This is the piece the ported kernel gets diffed against. Everything is blittable so
/// ctypes can drive it; strings come back one character at a time.
/// </summary>
// Split into partials by mechanism (see docs/spec/oracle-abi.md):
//   OracleExports.cs           - the original run/hash/observable ABI (unchanged, golden_v1 depends on it)
//   OracleExports.Random.cs    - the shuffle ABI
//   OracleExports.Extended.cs  - starting statuses, pools, multi-hit, multi-enemy, decrees, rich detail string
public static partial class OracleExports
{
    private static string _hash = string.Empty;
    private static string _error = string.Empty;
    private static int _steps;
    private static int _problems;
    private static int _heroHp;
    private static int _enemyHp;
    private static int _round;
    private static int _turn;
    private static int _randomStep;
    private static int _pending;
    private static int _logCount;

    // The canonical text CombatStateHasher actually feeds to SHA-256 (see HashCanonicalText.cs), plus the
    // flag saying our copy of the appender still reproduces the real hash.
    private static string _hashInput = string.Empty;
    private static int _hashInputOk;

    /// <summary>
    /// Records the pre-hash canonical text for a snapshot and SELF-CHECKS it: hashing our copy of the
    /// appender must reproduce <see cref="CombatStateHasher.ComputeHash"/>. A copied serializer that has
    /// drifted from upstream is then a visible 0 in rd_oracle_hash_input_ok() rather than plausible-looking
    /// text that no longer matches the hash it claims to explain.
    /// </summary>
    internal static void StoreHashInput(CombatStateSnapshot snapshot)
    {
        _hashInput = CanonicalHashInput.Build(snapshot);
        var digest = System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(_hashInput));
        var hex = Convert.ToHexString(digest).ToLowerInvariant();
        _hashInputOk = hex == CombatStateHasher.ComputeHash(snapshot) ? 1 : 0;
    }

    /// <summary>
    /// Authors a two-combatant fight, runs it, and stashes the resulting state hash.
    /// Returns the hash length, or -1 when the run failed (see rd_oracle_error_*).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_run")]
    public static int Run(int heroHp, int cardDamage, int enemyHp, int enemyDamage,
                          int seed, int variant)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _played = -1;
        try
        {
            var fight = new ScenarioBlueprint();

            fight.Cards.Add(new CardBlueprint("strike")
            {
                Program = Effects.Program(
                    Effects.DealDamage(CombatantTargetSelectors.EventTarget, cardDamage)),
            }.Cost(StandardCombatIds.EnergyResource, 1));

            fight.EnemyActions.Add(new EnemyActionBlueprint("smash",
                new ActionIntent("Smash", IntentKind.Attack))
            {
                Program = new EffectProgram<EnemyActionContext>(
                    new DealDamageNode<EnemyActionContext>(
                        CombatantTargetSelectors.EventTarget,
                        new ConstantExpression<EnemyActionContext>(enemyDamage))),
            });

            // variant >= 4 turns on the parts that actually consume randomness: a shuffled
            // draw pile, a turn-start energy refill, and a deck big enough to cycle.
            // WITHOUT THESE THE ENGINE NEVER DRAWS A RANDOM NUMBER - measured: RandomStep
            // stayed 0 across every case, so the corpus could not have caught RNG divergence,
            // which is the single most likely way a port goes wrong.
            var exerciseRng = variant >= 4;

            fight.Hero = new HeroBlueprint("knight") { MaxHealth = heroHp };
            fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId("strike"),
                                              Count: exerciseRng ? 12 : 3));
            fight.Hero.Resources.Add(
                new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));
            if (exerciseRng)
            {
                fight.ShuffleDrawPileOnStart = true;
                fight.TurnStartResourceRefills.Add(
                    new ResourceRefillSpec(StandardCombatIds.EnergyResource, 3));
            }

            var ogre = new EnemyBlueprint("ogre") { MaxHealth = enemyHp };
            ogre.Actions.Add(new EnemyActionDefinitionId("smash"));
            fight.Enemies.Add(ogre);

            var script = BuildScript(variant % 4);

            var report = new ScenarioRunner()
                .Run(new Playthrough(fight, script, combatId: "oracle", randomSeed: seed));

            var final = report.FinalState;
            var snapshot = final.CreateSnapshot();
            _hash = CombatStateHasher.ComputeHash(snapshot);
            StoreHashInput(snapshot);
            _steps = report.Steps.Count;
            _problems = report.HasProblems ? 1 : 0;
            _heroHp = final.GetCombatant(new CombatantId("knight")).Health.Current;
            _enemyHp = final.GetCombatant(new CombatantId("ogre")).Health.Current;
            _round = final.CurrentRound;
            _turn = final.CurrentTurn;
            _randomStep = final.RandomStep;
            _pending = final.PendingEffectCount;
            _logCount = final.CombatLog.Count;
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    private static IReadOnlyList<ScenarioStep> BuildScript(int variant) => variant switch
    {
        // 0: the README's own example - one card, end turn, one enemy action.
        0 => new ScenarioScript()
                .HeroPlays("strike", "ogre")
                .HeroEndsTurn()
                .EnemyActs("ogre", "smash", "knight")
                .Build(),

        // 1: same but the enemy swings twice - exercises repeat + death handling.
        1 => new ScenarioScript()
                .HeroPlays("strike", "ogre")
                .HeroEndsTurn()
                .EnemyActs("ogre", "smash", "knight")
                .EnemyActs("ogre", "smash", "knight")
                .Build(),

        // 2: play three cards then run a full round - exercises energy exhaustion,
        //    deck cycling and the round counter.
        2 => new ScenarioScript()
                .HeroPlays("strike", "ogre")
                .HeroPlays("strike", "ogre")
                .HeroPlays("strike", "ogre")
                .HeroEndsTurn()
                .NextRound()
                .HeroEndsTurn()
                .NextRound()
                .Build(),

        // 3: hero does nothing at all - the control case for the hash.
        3 => new ScenarioScript().HeroEndsTurn().NextRound().Build(),

        _ => new ScenarioScript().Build(),
    };

    // ---- hash ----

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hash_len")]
    public static int HashLen() => _hash.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hash_char")]
    public static int HashChar(int i) =>
        i >= 0 && i < _hash.Length ? _hash[i] : -1;

    // ---- observables ----

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_steps")]
    public static int Steps() => _steps;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_problems")]
    public static int Problems() => _problems;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hero_hp")]
    public static int HeroHp() => _heroHp;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_hp")]
    public static int EnemyHp() => _enemyHp;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_round")]
    public static int Round() => _round;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_turn")]
    public static int Turn() => _turn;

    /// <summary>
    /// The RNG cursor. The spec's finding is that the engine's whole random state is
    /// (RandomSeed, RandomStep) - so this number alone catches the most common porting bug
    /// of all: drawing a different NUMBER of random values, even when every value matches.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_random_step")]
    public static int RandomStep() => _randomStep;

    /// <summary>Effects still queued when the script ended. Should be 0 in a settled run.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_pending")]
    public static int Pending() => _pending;

    /// <summary>Combat log length - the appendix-only structure the spec flags as unbounded.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_log_count")]
    public static int LogCount() => _logCount;

    /// <summary>
    /// The exact bytes SHA-256 was given, one character at a time. Exported so a port can diff the canonical
    /// serialization LINE BY LINE instead of only learning that 64 hex characters disagree.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hash_input_len")]
    public static int HashInputLen() => _hashInput.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hash_input_char")]
    public static int HashInputChar(int i) =>
        i >= 0 && i < _hashInput.Length ? _hashInput[i] : -1;

    /// <summary>1 when our copy of the appender hashed to the engine's own hash for the same snapshot.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_hash_input_ok")]
    public static int HashInputOk() => _hashInputOk;

    // ---- error surface (so a failed run is diagnosable instead of a crash) ----

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_error_len")]
    public static int ErrorLen() => _error.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_error_char")]
    public static int ErrorChar(int i) =>
        i >= 0 && i < _error.Length ? _error[i] : -1;
}
