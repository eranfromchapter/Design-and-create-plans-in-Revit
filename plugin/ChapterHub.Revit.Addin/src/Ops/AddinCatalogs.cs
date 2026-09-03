using ChapterHub.Core;

namespace ChapterHub.Revit.Addin.Ops;

/// <summary>
/// The human-supplied MEP vocabulary, the shared clash table and (Phase 7) the set_parameter
/// allowlist as enrolled on the Revit machine (%AppData%\ChapterHub\catalogs\{mep_types,
/// clash_prisms,param_allowlist}.json — copied from packages/contracts at enrollment,
/// docs/MANUAL_REVIT_TEST.md). Absent files leave the dependent handlers failing CLEANLY with
/// catalog_missing (rolled_back), never guessing a family name or a parameter rule.
/// </summary>
public sealed class AddinCatalogs
{
    public MepTypes? MepTypes { get; init; }
    public ClashExemptions? Clash { get; init; }
    public ParamAllowlist? Params { get; init; }

    public static readonly AddinCatalogs Empty = new();

    /// <summary>Each file is parsed on its own: a malformed param_allowlist.json leaves the
    /// MEP catalogs usable (and vice versa) — the affected ops fail catalog_missing, nothing else.</summary>
    public static AddinCatalogs Load(string directory) => new()
    {
        MepTypes = LoadOne(Path.Combine(directory, "mep_types.json"), MepTypes.FromJson),
        Clash = LoadOne(Path.Combine(directory, "clash_prisms.json"), ClashExemptions.FromJson),
        Params = LoadOne(Path.Combine(directory, "param_allowlist.json"), ParamAllowlist.FromJson),
    };

    private static T? LoadOne<T>(string path, Func<string, T> parse) where T : class
    {
        if (!File.Exists(path)) return null;
        try
        {
            return parse(File.ReadAllText(path));
        }
        catch (Exception)
        {
            return null;
        }
    }

    public MepTypes RequireMepTypes() =>
        MepTypes ?? throw new OpFailure("catalog_missing", "mep_types.json is not enrolled on this machine");

    public ClashExemptions RequireClash() =>
        Clash ?? throw new OpFailure("catalog_missing", "clash_prisms.json is not enrolled on this machine");

    public ParamAllowlist RequireParamAllowlist() =>
        Params ?? throw new OpFailure("catalog_missing", "param_allowlist.json is not enrolled on this machine");
}
