using ChapterHub.Core.Contracts;

namespace ChapterHub.Core;

/// <summary>Raised when a pipe/conduit path cannot be built from standard fittings
/// (codes: too_few_points, zero_length, fitting_unsupported) — the executor fails the op.</summary>
public sealed class PipePathError(string code, string message) : Exception($"{code}: {message}")
{
    public string Code { get; } = code;
}

/// <summary>
/// Pipe/conduit path classification (Phase 6) — the C# twin of the layout-compiler's
/// mep/fittings.py, both pinned by packages/contracts/fixtures/pipepath/manifest.json:
/// consecutive collinear segments merge; a bend within AngleToleranceDeg of 90 or 45 is a
/// standard elbow; any other bend is fitting_unsupported (v1 emits REVIEW for tees/wyes);
/// a segment shorter than MinSegmentMm is zero_length. All coordinates mm, 3D.
/// </summary>
public static class PipePath
{
    public const double AngleToleranceDeg = 0.5;
    public const double CollinearToleranceDeg = 0.5;
    public const double MinSegmentMm = 1e-6;

    /// <summary>Merged polyline + the elbow angle (90 or 45) at every interior point.</summary>
    public sealed record Classification(IReadOnlyList<Pt3> Points, IReadOnlyList<int> BendsDeg)
    {
        public int Segments => Points.Count - 1;
    }

    public static Classification Classify(
        IReadOnlyList<Pt3> path,
        double angleToleranceDeg = AngleToleranceDeg,
        double collinearToleranceDeg = CollinearToleranceDeg,
        double minSegmentMm = MinSegmentMm)
    {
        if (path.Count < 2) throw new PipePathError("too_few_points", $"{path.Count} point(s)");
        for (var i = 1; i < path.Count; i++)
            if (Length(Sub(path[i], path[i - 1])) < minSegmentMm)
                throw new PipePathError("zero_length", $"segment at {Format(path[i - 1])}");

        var merged = new List<Pt3> { path[0] };
        for (var i = 1; i < path.Count - 1; i++)
        {
            var u = Sub(path[i], merged[^1]);
            var v = Sub(path[i + 1], path[i]);
            if (AngleDeg(u, v) <= collinearToleranceDeg) continue; // collinear run: drop the interior point
            merged.Add(path[i]);
        }
        merged.Add(path[^1]);

        var bends = new List<int>();
        for (var i = 1; i < merged.Count - 1; i++)
        {
            var angle = AngleDeg(Sub(merged[i], merged[i - 1]), Sub(merged[i + 1], merged[i]));
            if (Math.Abs(angle - 90.0) <= angleToleranceDeg) bends.Add(90);
            else if (Math.Abs(angle - 45.0) <= angleToleranceDeg) bends.Add(45);
            else throw new PipePathError("fitting_unsupported", $"{angle:F1} deg bend at {Format(merged[i])}");
        }
        return new Classification(merged, bends);
    }

    private static Pt3 Sub(Pt3 a, Pt3 b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);

    private static double Length(Pt3 v) => Math.Sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z);

    private static double AngleDeg(Pt3 u, Pt3 v)
    {
        var cos = (u.X * v.X + u.Y * v.Y + u.Z * v.Z) / (Length(u) * Length(v));
        return Math.Acos(Math.Clamp(cos, -1.0, 1.0)) * 180.0 / Math.PI;
    }

    private static string Format(Pt3 p) => $"({p.X}, {p.Y}, {p.Z})";
}
