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

    public static AddinCatalogs Load(string directory)
    {
        var mep = Path.Combine(directory, "mep_types.json");
        var clash = Path.Combine(directory, "clash_prisms.json");
        var allowlist = Path.Combine(directory, "param_allowlist.json");
        return new AddinCatalogs
        {
            MepTypes = File.Exists(mep) ? MepTypes.FromJson(File.ReadAllText(mep)) : null,
            Clash = File.Exists(clash) ? ClashExemptions.FromJson(File.ReadAllText(clash)) : null,
            Params = File.Exists(allowlist) ? ParamAllowlist.FromJson(File.ReadAllText(allowlist)) : null,
        };
    }

    public MepTypes RequireMepTypes() =>
        MepTypes ?? throw new OpFailure("catalog_missing", "mep_types.json is not enrolled on this machine");

    public ClashExemptions RequireClash() =>
        Clash ?? throw new OpFailure("catalog_missing", "clash_prisms.json is not enrolled on this machine");

    public ParamAllowlist RequireParamAllowlist() =>
        Params ?? throw new OpFailure("catalog_missing", "param_allowlist.json is not enrolled on this machine");
}
