using ChapterHub.Core;

namespace ChapterHub.Revit.Addin.Ops;

/// <summary>
/// The human-supplied MEP vocabulary and the shared clash table as enrolled on the Revit
/// machine (%AppData%\ChapterHub\catalogs\{mep_types,clash_prisms}.json — copied from
/// packages/contracts/catalogs at enrollment, docs/MANUAL_REVIT_TEST.md). Absent files
/// leave the MEP handlers failing CLEANLY with catalog_missing (rolled_back), never
/// guessing a family name.
/// </summary>
public sealed class AddinCatalogs
{
    public MepTypes? MepTypes { get; init; }
    public ClashExemptions? Clash { get; init; }

    public static readonly AddinCatalogs Empty = new();

    public static AddinCatalogs Load(string directory)
    {
        var mep = Path.Combine(directory, "mep_types.json");
        var clash = Path.Combine(directory, "clash_prisms.json");
        return new AddinCatalogs
        {
            MepTypes = File.Exists(mep) ? MepTypes.FromJson(File.ReadAllText(mep)) : null,
            Clash = File.Exists(clash) ? ClashExemptions.FromJson(File.ReadAllText(clash)) : null,
        };
    }

    public MepTypes RequireMepTypes() =>
        MepTypes ?? throw new OpFailure("catalog_missing", "mep_types.json is not enrolled on this machine");

    public ClashExemptions RequireClash() =>
        Clash ?? throw new OpFailure("catalog_missing", "clash_prisms.json is not enrolled on this machine");
}
