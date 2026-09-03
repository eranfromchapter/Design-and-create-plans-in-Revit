namespace ChapterHub.Core;

/// <summary>
/// Trade-size binding for create_pipe / create_conduit diameters. The contracts carry nominal
/// sizes in mm (Part G: Ø51 / Ø76 stacks, plumbing.json drain diameters 32/38/51/76,
/// mep_types.json conduit_diameter_mm) while Revit binds OD/ID only when the written value is
/// exactly a size of the type's segment / conduit-standard table (76.2 = 3", 50.8 = 2",
/// 19.05 = ¾" EMT). The live spike (docs/REVIT_SPIKE_RESULTS.md steps 4–5) showed a literal
/// 76 mm producing OD = ID = 76 and 21 mm shown as "7/8"" — no table binding at all. The
/// executor therefore snaps to the nearest table nominal within SnapToleranceMm and fails
/// `unknown_size` otherwise; a type without any table keeps the literal value.
/// </summary>
public static class MepSizes
{
    /// <summary>Imperial nominals are ≥ 6.35 mm apart and metric DN steps ≥ 5 mm, so 2.5 mm
    /// can never reach two nominals of one table except at an exact midpoint (→ smaller).</summary>
    public const double SnapToleranceMm = 2.5;

    /// <summary>The table nominal nearest to the request when within the tolerance (ties → the
    /// smaller), else null; an empty table yields null too.</summary>
    public static double? Snap(double requestedMm, IEnumerable<double> nominalsMm, double toleranceMm = SnapToleranceMm)
    {
        double? best = null;
        foreach (var nominal in nominalsMm)
        {
            var distance = Math.Abs(nominal - requestedMm);
            if (distance > toleranceMm) continue;
            if (best is null)
            {
                best = nominal;
                continue;
            }
            var bestDistance = Math.Abs(best.Value - requestedMm);
            if (distance < bestDistance || (distance == bestDistance && nominal < best.Value)) best = nominal;
        }
        return best;
    }

    /// <summary>The nearest table nominal regardless of tolerance (for failure messages); null
    /// for an empty table.</summary>
    public static double? Nearest(double requestedMm, IEnumerable<double> nominalsMm) =>
        Snap(requestedMm, nominalsMm, double.PositiveInfinity);
}
