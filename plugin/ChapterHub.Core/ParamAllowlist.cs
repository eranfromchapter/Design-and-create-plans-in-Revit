using System.Text.Json;

namespace ChapterHub.Core;

/// <summary>
/// packages/contracts/ops/param_allowlist.json as the plugin sees it (SI-4): the ONLY
/// parameters set_parameter may touch, each with the category vocabulary it applies to
/// (walls, doors, windows, furniture, casework, plumbing, electrical; "*" = any). Enrolled
/// beside the MEP catalogs; the gateway checks the same file by target-id prefix before
/// signing and revit-sim by record category — three independent enforcers, one source.
/// </summary>
public sealed class ParamAllowlist
{
    public sealed record Entry(string Name, string Kind, IReadOnlyList<string> Categories);

    public static readonly IReadOnlySet<string> Vocabulary = new HashSet<string>
    {
        "walls", "doors", "windows", "furniture", "casework", "plumbing", "electrical",
    };

    private readonly IReadOnlyDictionary<string, Entry> _byName;

    public string AllowlistVersion { get; }
    public IReadOnlyList<Entry> Entries { get; }

    private ParamAllowlist(string version, IReadOnlyList<Entry> entries)
    {
        AllowlistVersion = version;
        Entries = entries;
        _byName = entries.ToDictionary(e => e.Name);
    }

    public static ParamAllowlist FromJson(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var entries = root.GetProperty("params").EnumerateArray().Select(p =>
        {
            var categories = p.GetProperty("categories").EnumerateArray().Select(c => c.GetString()!).ToList();
            foreach (var c in categories)
                if (c != "*" && !Vocabulary.Contains(c))
                    throw new JsonException($"param_allowlist: unknown category {c}");
            return new Entry(p.GetProperty("name").GetString()!, p.GetProperty("kind").GetString()!, categories);
        }).ToList();
        return new ParamAllowlist(root.GetProperty("allowlist_version").GetString()!, entries);
    }

    public bool Contains(string param) => _byName.ContainsKey(param);

    public string? Kind(string param) => _byName.TryGetValue(param, out var e) ? e.Kind : null;

    /// <summary>Allowed when the param is listed and either carries "*" or names the target's
    /// category; a target with no vocabulary category (null) may only take "*" params.</summary>
    public bool IsAllowed(string param, string? category)
    {
        if (!_byName.TryGetValue(param, out var entry)) return false;
        if (entry.Categories.Contains("*")) return true;
        return category is not null && entry.Categories.Contains(category);
    }

    /// <summary>Finish/product/spec/comment params carry text: the value the executor writes
    /// must be a string (revit-sim's param_type_mismatch rule).</summary>
    public bool RequiresString(string param) =>
        Kind(param) is "finish" or "product" or "spec" or "comment";
}
