using System.Runtime.InteropServices;
using System.Text;
using RogueDeck.Core.Combat;

namespace RogueDeck.Oracle;

/// <summary>
/// The RNG surface of the oracle: the engine's <c>CombatRandom</c> shuffle, exposed index by index.
///
/// WHY THE WHOLE SEQUENCE IS ALWAYS COMPUTED
/// -----------------------------------------
/// The obvious "optimisation" for a single-index export is to run the Fisher-Yates loop only as far as
/// the requested index and break. That is WRONG and the spec calls it out explicitly: the loop consumes
/// one draw per position, so stopping early produces a DIFFERENT sequence than the engine's. Every entry
/// point here goes through <see cref="CombatRandom.CreateShuffledIndexes"/> - the engine's own function -
/// and indexes the result, so the numbers handed to a port are bit-identical to the ones the engine uses.
/// </summary>
public static partial class OracleExports
{
    private static string _shuffleText = string.Empty;

    /// <summary>
    /// Entry i of the engine's shuffled index sequence.
    /// <c>CreateShuffledIndexes(count, seed, step)[i]</c>, or -1 when count/index are out of range.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_shuffle")]
    public static int Shuffle(int count, int seed, int step, int i)
    {
        try
        {
            if (count < 0 || i < 0 || i >= count)
                return -1;

            var order = CombatRandom.CreateShuffledIndexes(count, seed, step);
            return order[i];
        }
        catch (Exception)
        {
            return -1;
        }
    }

    /// <summary>
    /// The whole shuffled sequence, as <c>"a,b,c"</c>, for dumping a port's shuffle table in one go.
    /// Returns the string length (or -1 when count is out of range); read it with
    /// <c>rd_oracle_shuffle_text_char</c>.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_shuffle_text")]
    public static int ShuffleText(int count, int seed, int step)
    {
        _shuffleText = string.Empty;
        try
        {
            if (count < 0 || count > 4096)
                return -1;

            var order = CombatRandom.CreateShuffledIndexes(count, seed, step);
            var text = new StringBuilder();
            for (var i = 0; i < order.Count; i++)
            {
                if (i > 0)
                    text.Append(',');
                text.Append(order[i]);
            }
            _shuffleText = text.ToString();
            return _shuffleText.Length;
        }
        catch (Exception)
        {
            return -1;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_shuffle_text_char")]
    public static int ShuffleTextChar(int i) =>
        i >= 0 && i < _shuffleText.Length ? _shuffleText[i] : -1;
}
