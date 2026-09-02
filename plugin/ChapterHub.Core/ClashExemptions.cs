using System.Text.Json;

namespace ChapterHub.Core;

/// <summary>
/// The plugin's half of the ONE clash law (PLAN.md Part G clash priority): the exemption
/// pairs and priorities from packages/contracts/catalogs/clash_prisms.json — the same
/// file the layout-compiler merge gate (Phase A) and revit-sim read. Classes:
/// structure | pipe | conduit | device | furniture (walls, doors and windows are never
/// clash elements). `pipe_serves_fixture` cannot be resolved by an executor (ops carry
/// no served-fixture id) and is deliberately NOT applied — the executor is strict there,
/// exactly like the sim; the merge gate resolves it in Phase A.
/// </summary>
public sealed class ClashExemptions
{
    public sealed record Rule(string A, string B, string? When);

    public static readonly IReadOnlyList<string> Classes = ["structure", "pipe", "conduit", "device", "furniture"];

    public IReadOnlyList<Rule> Rules { get; }
    public IReadOnlyDictionary<string, int> Priorities { get; }

    private ClashExemptions(IReadOnlyList<Rule> rules, IReadOnlyDictionary<string, int> priorities)
    {
        Rules = rules;
        Priorities = priorities;
    }

    public static ClashExemptions FromJson(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var rules = doc.RootElement.GetProperty("exempt_pairs").EnumerateArray()
            .Select(r => new Rule(
                r.GetProperty("a").GetString()!,
                r.GetProperty("b").GetString()!,
                r.TryGetProperty("when", out var when) ? when.GetString() : null))
            .ToArray();
        var priorities = doc.RootElement.GetProperty("priorities").EnumerateObject()
            .ToDictionary(p => p.Name, p => p.Value.GetInt32());
        return new ClashExemptions(rules, priorities);
    }

    /// <summary>True when the pair never counts as a clash. Symmetric.</summary>
    public bool IsExempt(string classA, string? systemA, string classB, string? systemB)
    {
        foreach (var rule in Rules)
        {
            if (rule.A == rule.B)
            {
                if (!(classA == rule.A && classB == rule.A)) continue;
            }
            else if (!((classA == rule.A && classB == rule.B) || (classA == rule.B && classB == rule.A)))
            {
                continue;
            }
            switch (rule.When)
            {
                case null:
                    return true;
                case "same_system":
                    return systemA is not null && systemA == systemB;
                case "pipe_serves_fixture":
                    continue; // unresolvable in an executor → strict (see class summary)
                default:
                    continue;
            }
        }
        return false;
    }

    /// <summary>Clash priority: structure 0, sanitary/vent 1, supply 2, hvac 3,
    /// electrical 4, furniture 5. Pipes take their system's priority.</summary>
    public int Priority(string cls, string? system) => cls switch
    {
        "structure" => Priorities["structure"],
        "pipe" => Priorities.TryGetValue(system ?? "sanitary", out var p) ? p : Priorities["sanitary"],
        "conduit" or "device" => Priorities["electrical"],
        "furniture" => Priorities["furniture"],
        _ => throw new ArgumentException($"unknown clash class '{cls}'", nameof(cls)),
    };
}
