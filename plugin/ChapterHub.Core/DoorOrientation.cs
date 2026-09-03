using ChapterHub.Core.Contracts;

namespace ChapterHub.Core;

/// <summary>
/// Door hand/facing law for the Revit executor. The Phase 5 convention (layout-compiler
/// swing.py, the arcs every card and every validator verdict are built on): the hinge jamb
/// sits at offset − w/2 — toward the host wall's START — for swing "L" and at offset + w/2
/// for "R"; the leaf sweeps into the LEFT side of start→end (+90° CCW) when flip_facing is
/// falsy and into the RIGHT side when true.
///
/// Revit's HandFlipped/FacingFlipped flags are relative to the family's authoring AND to
/// Wall.Orientation (a fresh door faces the wall's exterior, which Wall.Flipped negates), so
/// the executor never reads the flags: it compares the placed instance's HandOrientation /
/// FacingOrientation with the desired world directions and flips on a negative dot product
/// (live spike 2026-09-03, docs/REVIT_SPIKE_RESULTS.md step 3).
///
/// Declared family convention — the one fact stage 1 of the spike could not exercise live;
/// stage 2 verifies it against Chapter's real door family: the leaf is hinged at the
/// family's −X jamb and swings to family +Y (Exterior), so HandOrientation points
/// hinge → latch and FacingOrientation is the swept side.
/// </summary>
public static class DoorOrientation
{
    public readonly record struct Vec2(double X, double Y);

    /// <summary>World directions (XY, unit length) the placed instance must show.</summary>
    public readonly record struct Desired(Vec2 Hand, Vec2 Facing);

    public static Desired For(Pt2 start, Pt2 end, string swing, bool flipFacing)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var length = Math.Sqrt(dx * dx + dy * dy);
        if (length == 0) throw new ArgumentException("zero-length wall", nameof(end));
        var (ux, uy) = (dx / length, dy / length);
        var hand = swing switch
        {
            "L" => new Vec2(ux, uy), // hinge toward start: hinge → latch runs along start→end
            "R" => new Vec2(-ux, -uy),
            _ => throw new ArgumentException($"unknown swing '{swing}'", nameof(swing)),
        };
        var left = new Vec2(-uy, ux);
        var facing = flipFacing ? new Vec2(-left.X, -left.Y) : left;
        return new Desired(hand, facing);
    }

    /// <summary>+1 when the actual direction agrees with the desired one, −1 when it points the
    /// other way (flip), 0 when it is perpendicular or degenerate (a family authored off the
    /// wall axis — the executor fails the op rather than guessing). Z is ignored.</summary>
    public static int Sign(Vec2 actual, Vec2 desired)
    {
        var dot = actual.X * desired.X + actual.Y * desired.Y;
        return Math.Abs(dot) < 1e-6 ? 0 : Math.Sign(dot);
    }
}
