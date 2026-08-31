using ChapterHub.Core.Contracts;

namespace ChapterHub.Core;

/// <summary>
/// Shared placement math (Part G projection primitive specialized to offset-along-wall),
/// in millimeters. Pinned against packages/contracts/fixtures/placement/manifest.json;
/// the Python twin is revit_sim.placement — Phase 1 acceptance requires both to agree
/// to 1e-6 mm. The Addin's op handlers convert the result with UnitConversion.MmToFt.
/// </summary>
public static class Placement
{
    public readonly record struct Point3(double X, double Y, double Z);

    /// <param name="kind">"centerline" | "face_left" | "face_right" (the fixture vocabulary);
    /// left = +90° CCW of the start→end direction.</param>
    public static Point3 Place(
        string kind, Pt2 start, Pt2 end, double thicknessMm, double offsetMm, double zMm)
    {
        var (ux, uy) = Unit(start, end);
        var cx = start.X + ux * offsetMm;
        var cy = start.Y + uy * offsetMm;
        switch (kind)
        {
            case "centerline":
                return new Point3(cx, cy, zMm);
            case "face_left":
            case "face_right":
            {
                var (nx, ny) = (-uy, ux); // left normal
                if (kind == "face_right") (nx, ny) = (-nx, -ny);
                var half = thicknessMm / 2.0;
                return new Point3(cx + nx * half, cy + ny * half, zMm);
            }
            default:
                throw new ArgumentException($"unknown placement kind '{kind}'", nameof(kind));
        }
    }

    private static (double Ux, double Uy) Unit(Pt2 start, Pt2 end)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var length = Math.Sqrt(dx * dx + dy * dy);
        if (length == 0) throw new ArgumentException("zero-length wall");
        return (dx / length, dy / length);
    }
}
