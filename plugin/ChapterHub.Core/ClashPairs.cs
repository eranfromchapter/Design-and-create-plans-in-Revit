namespace ChapterHub.Core;

/// <summary>
/// Interference reporting (Phase 6): the executor names clashing elements by their
/// LOGICAL ids so the merge gate can re-plan them. Reverse lookup runs over the
/// envelope's created delta first, then the persisted id-map; an element the HUB never
/// created (a modelled column, existing MEP) is reported as revit:&lt;ElementId&gt;, which
/// the merge gate treats as structure (priority 0 — it never moves).
/// </summary>
public static class ClashPairs
{
    public const string Separator = "~";
    public const string RevitPrefix = "revit:";

    public static string LogicalId(
        long elementId,
        IReadOnlyDictionary<string, long> idMap,
        IReadOnlyList<(string LogicalId, long ElementId)> delta)
    {
        foreach (var (logicalId, id) in delta)
            if (id == elementId) return logicalId;
        foreach (var (logicalId, id) in idMap)
            if (id == elementId) return logicalId;
        return RevitPrefix + elementId;
    }

    /// <summary>The interference error message: "A~B" (created element first).</summary>
    public static string Format(string aId, string bId) => aId + Separator + bId;

    /// <summary>Parse "A~B"; null when the message is not a pair.</summary>
    public static (string AId, string BId)? Parse(string message)
    {
        var parts = message.Split(Separator);
        if (parts.Length != 2 || parts[0].Length == 0 || parts[1].Length == 0) return null;
        return (parts[0], parts[1]);
    }
}
