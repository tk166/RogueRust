using System.Runtime.InteropServices;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// Death-prevention: the S6 stage of the damage pipeline, where a lethal blow is asked about before it lands.
///
/// WHY THE ORACLE HAS TO BRING ITS OWN INTERCEPTORS: <c>IPreDownInterceptor</c> is a public interface, but
/// RogueDeck.Core ships NO implementation of it - the only one in the repository lives in
/// RogueDeck.Sandbox.Combat and is internal, so an oracle that did not write one could not exercise this
/// mechanism at all. These two are deliberately minimal and, like the cited test interceptors, mutate the
/// marker status synchronously inside Intercept() (the engine removes a status whose charges reach 0).
/// </summary>
internal sealed class PhoenixStyleInterceptor(StatusDefinitionId marker) : IPreDownInterceptor
{
    public string InterceptorId => "oracle.phoenix";

    public int Priority => 100;

    public PreDownInterceptionResult Intercept(PreDownInterceptionContext context)
    {
        var bearer = context.Target;
        var mark = bearer.Statuses.FirstOrDefault(status =>
            status.DefinitionId == marker && status.Charges > 0);
        if (mark is null)
            return PreDownInterceptionResult.Allow;

        mark.SetCharges(mark.Charges - 1);
        return PreDownInterceptionResult.Prevent(Math.Max(1, bearer.Health.Max / 2));
    }
}

internal sealed class MartyrStyleInterceptor(StatusDefinitionId marker) : IPreDownInterceptor
{
    public string InterceptorId => "oracle.martyr";

    public int Priority => 100;

    public PreDownInterceptionResult Intercept(PreDownInterceptionContext context)
    {
        foreach (var combatant in context.Combat.Combatants)
        {
            if (combatant.Id == context.Target.Id || combatant.TeamId != context.Target.TeamId)
                continue;
            if (combatant.Statuses.Any(status => status.DefinitionId == marker && status.Stacks > 0))
                return PreDownInterceptionResult.Redirect(combatant.Id);
        }
        return PreDownInterceptionResult.Allow;
    }
}

public static partial class OracleExports
{
    private static readonly StatusDefinitionId PhoenixMarker = new("oracle.phoenix");
    private static readonly StatusDefinitionId MartyrMarker = new("oracle.martyr");

    /// <summary>
    /// kind 0 = Phoenix: the hero stands at 40/50 wearing a 1-charge marker, and the card lands
    /// <paramref name="hits"/> hits of 100. The first lethal blow is Prevent(Max/2) and eats the charge, so
    /// the hero is left at 25; hits = 2 kills them outright the second time.
    /// kind 1 = Martyr: the 5-HP hero is hit for 10 and a 50/50 ally wearing the marker takes the whole blow
    /// (Redirect) - the hero is untouched at 5 and the protector drops to 40.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_pre_down")]
    public static int ProbePreDown(int kind, int hits, int seed)
    {
        try
        {
            if (kind == 0)
            {
                var phoenix = new StatusBlueprint("oracle.phoenix")
                {
                    Polarity = StatusPolarity.Buff,
                    UsesCharges = true,
                };
                var program = new EffectProgram<CardPlayContext>(new SequenceEffectNode<CardPlayContext>(
                    Enumerable.Range(0, Math.Max(1, hits)).Select(_ =>
                        (IEffectNode<CardPlayContext>)new DealDamageNode<CardPlayContext>(
                            CombatantTargetSelectors.Source, Effects.Const(100))).ToList()));

                var fight = NewFight(50, 200, 1, 3, 5, new NoOpEffectNode<CardPlayContext>(), 0, false);
                fight.Cards.Clear();
                fight.Cards.Add(new CardBlueprint(CardId) { Program = program }
                    .Cost(StandardCombatIds.EnergyResource, 0));
                var hero = new HeroBlueprint(HeroId) { MaxHealth = 50, CurrentHealth = 40 };
                hero.Deck.Add(new DeckEntry(new CardDefinitionId(CardId), Count: 3));
                hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, 3, 3));
                hero.StartingStatuses.Add(new StartingStatusSpec(phoenix.DefinitionId, Charges: 1));
                fight.Hero = hero;
                fight.Statuses.Add(phoenix);
                fight.PreDownInterceptors.Add(new PhoenixStyleInterceptor(phoenix.DefinitionId));

                var report = RunFight(fight, PlayOnce(), seed);
                if (report is null)
                    return -1;
                Capture(report);
                return _hash.Length;
            }

            var martyr = new StatusBlueprint("oracle.martyr")
            {
                Polarity = StatusPolarity.Buff,
                UsesStacks = true,
            };
            var martyrFight = NewFight(5, 200, 1, 3, 5,
                new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.Source, Effects.Const(10)),
                cardCost: 0, shuffle: false);
            martyrFight.Statuses.Add(martyr);
            var protector = new AllyBlueprint("protector") { MaxHealth = 50 };
            protector.StartingStatuses.Add(new StartingStatusSpec(martyr.DefinitionId, Stacks: 1));
            martyrFight.Allies.Add(protector);
            martyrFight.PreDownInterceptors.Add(new MartyrStyleInterceptor(martyr.DefinitionId));

            var martyrReport = RunFight(martyrFight, PlayOnce(), seed);
            if (martyrReport is null)
                return -1;
            Capture(martyrReport);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }
}
