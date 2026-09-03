namespace ChapterHub.Core;

/// <summary>
/// Revit BuiltInCategory → the allowlist's category vocabulary (SI-4). Core has no Revit
/// reference, so the Addin hands over the enum NAME (BuiltInCategory.ToString()). Categories
/// outside this table have no vocabulary word: only "*" params (Comments) may touch them.
/// </summary>
public static class ParamCategories
{
    private static readonly IReadOnlyDictionary<string, string> Table = new Dictionary<string, string>
    {
        ["OST_Walls"] = "walls",
        ["OST_Doors"] = "doors",
        ["OST_Windows"] = "windows",
        ["OST_Casework"] = "casework",
        ["OST_PlumbingFixtures"] = "plumbing",
        ["OST_ElectricalFixtures"] = "electrical",
        ["OST_LightingDevices"] = "electrical",
        ["OST_ElectricalEquipment"] = "electrical",
        ["OST_Furniture"] = "furniture",
        ["OST_FurnitureSystems"] = "furniture",
        ["OST_SpecialityEquipment"] = "furniture",
    };

    public static string? Vocabulary(string? builtInCategoryName) =>
        builtInCategoryName is not null && Table.TryGetValue(builtInCategoryName, out var v) ? v : null;
}
