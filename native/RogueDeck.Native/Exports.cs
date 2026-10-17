using System.Runtime.InteropServices;
using RogueDeck.Core.Combat;

namespace RogueDeck.Native;

/// <summary>
/// C ABI surface over the real engine. Every exported method is
/// <c>[UnmanagedCallersOnly]</c> and blittable, so ctypes can call it directly.
///
/// The body mirrors <c>RogueDeck.ConsoleSandbox/Program.cs</c>: build a registry from the
/// standard package, declare a Strike-equivalent card, stand up a two-combatant fight,
/// play the card, hash the state. If this survives NativeAOT, the whole Core library does.
/// </summary>
public static class Exports
{
    private static string _lastHash = string.Empty;
    private static int _lastGoblinHp;
    private static int _lastHeroHp;
    private static int _lastEnergy;

    /// <summary>
    /// Runs one fight: hero 30 HP / 3 energy, goblin 12 HP, one card dealing
    /// <paramref name="damage"/>, optionally 2 stacks of poison on the hero first.
    /// Returns the goblin's remaining HP, and stashes the state hash for rd_hash_*.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_probe")]
    public static int Probe(int seed, int damage, int poisonStacks)
    {
        var (hash, goblinHp, heroHp, energy) = RunOnce(seed, damage, poisonStacks);
        _lastHash = hash;
        _lastGoblinHp = goblinHp;
        _lastHeroHp = heroHp;
        _lastEnergy = energy;
        return goblinHp;
    }

    /// <summary>Length of the state-hash string produced by the last rd_probe.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_hash_len")]
    public static int HashLen() => _lastHash.Length;

    /// <summary>i-th character of that hash, as an int. -1 when out of range.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_hash_char")]
    public static int HashChar(int index) =>
        index >= 0 && index < _lastHash.Length ? _lastHash[index] : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_hero_hp")]
    public static int HeroHp() => _lastHeroHp;

    [UnmanagedCallersOnly(EntryPoint = "rd_energy")]
    public static int Energy() => _lastEnergy;

    [UnmanagedCallersOnly(EntryPoint = "rd_goblin_hp")]
    public static int GoblinHp() => _lastGoblinHp;

    /// <summary>1 when the same seed reproduces the same final state hash, 0 otherwise.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_determinism")]
    public static int Determinism(int seed, int damage, int poisonStacks)
    {
        var first = RunOnce(seed, damage, poisonStacks).Hash;
        var second = RunOnce(seed, damage, poisonStacks).Hash;
        return first == second ? 1 : 0;
    }

    /// <summary>1 when a different seed changes the final hash (the RNG is actually wired in).</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_seed_sensitivity")]
    public static int SeedSensitivity(int seedA, int seedB, int damage, int poisonStacks)
    {
        var a = RunOnce(seedA, damage, poisonStacks).Hash;
        var b = RunOnce(seedB, damage, poisonStacks).Hash;
        return a == b ? 0 : 1;
    }

    /// <summary>
    /// The engine's shuffle, exposed one index at a time so a ported kernel can be diffed
    /// against it. Source: CombatRandom.CreateShuffledIndexes(count, randomSeed, randomStep)
    /// - a Mulberry32 variant whose entire persistent state is (seed, step).
    ///
    /// Note the engine always builds the WHOLE sequence before returning, and the spec warns
    /// that an early "I only need index 0" break changes the result: index 0 is the outcome of
    /// the full Fisher-Yates pass, not of a single draw. So this walks the whole array too.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_rng_shuffle")]
    public static int Shuffle(int count, int seed, int step, int index)
    {
        if (count < 0 || index < 0 || index >= count)
            return -1;
        var indexes = CombatRandom.CreateShuffledIndexes(count, seed, step);
        return index < indexes.Count ? indexes[index] : -1;
    }

    /// <summary>How many indexes CreateShuffledIndexes returns - the port must agree on this too.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_rng_shuffle_len")]
    public static int ShuffleLen(int count, int seed, int step) =>
        count <= 0 ? 0 : CombatRandom.CreateShuffledIndexes(count, seed, step).Count;

    /// <summary>A value that only a live engine can produce: the standard package's card count.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_standard_definition_count")]
    public static int StandardDefinitionCount()
    {
        var builder = new CombatDefinitionRegistryBuilder();
        new StandardCombatPackage().RegisterDefinitions(builder);
        return builder.Build().CardDefinitions.Count;
    }

    private static (string Hash, int GoblinHp, int HeroHp, int Energy) RunOnce(
        int seed, int damage, int poisonStacks)
    {
        var builder = new CombatDefinitionRegistryBuilder();
        new StandardCombatPackage().RegisterDefinitions(builder);

        var strikeId = new CardDefinitionId("demo.strike");
        var strike = new CardDefinitionBuilder(
            strikeId,
            new PackageId("demo"),
            displayNameKey: "card.demo.strike.name",
            descriptionKey: "card.demo.strike.description");
        strike.Costs.Add(new ResourceCost(StandardCombatIds.EnergyResource, 1));
        strike.Tags.Add(StandardCombatIds.AttackCardTag);
        strike.Effects.Add(new DealDamageEffectRecipe<CardPlayContext>(
            CombatantTargetSelectors.EventTarget,
            new FixedCombatValue<int>(damage)));
        builder.RegisterCard(strike);

        var registry = builder.Build();

        var combat = new CombatState(new CombatId("aot_probe"), randomSeed: seed);

        var hero = new CombatantState(
            new CombatantId("hero"),
            new CombatantDefinitionId("standard.hero"),
            "combatant.hero",
            StandardCombatIds.PlayerTeam,
            new HealthState(current: 30, max: 30));
        hero.AddResource(StandardCombatIds.EnergyResource, new ValuePoolState(current: 3, max: 3));

        var goblin = new CombatantState(
            new CombatantId("goblin"),
            new CombatantDefinitionId("standard.goblin"),
            "combatant.goblin",
            StandardCombatIds.EnemyTeam,
            new HealthState(current: 12, max: 12));

        combat.AddCombatant(hero);
        combat.AddCombatant(goblin);

        if (poisonStacks > 0)
        {
            combat.EnqueueEffect(new ApplyStatusEffectRequest(
                new CombatantId("hero"),
                new StatusDefinitionId("standard.poison"),
                Stacks: poisonStacks));
            new CombatQueueProcessor().ResolvePendingQueues(combat, registry);
        }

        var card = new CardInstance(
            combat.CreateNextCardInstanceId(),
            strikeId,
            new CombatantId("hero"),
            CardZone.Hand);
        combat.GetCardZones(new CombatantId("hero")).AddCard(card);

        var runner = new CombatReplayRunner();
        var heroId = new CombatantId("hero");
        var goblinId = new CombatantId("goblin");

        runner.Apply(combat, registry, new PlayCardCommand(heroId, card.Id, goblinId));
        runner.Apply(combat, registry, new EndTurnCommand(heroId));

        var hash = CombatStateHasher.ComputeHash(combat.CreateSnapshot());
        return (
            hash,
            combat.GetCombatant(goblinId).Health.Current,
            combat.GetCombatant(heroId).Health.Current,
            combat.GetCombatant(heroId).Resources[StandardCombatIds.EnergyResource].Current);
    }
}
