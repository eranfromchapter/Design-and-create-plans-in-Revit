using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>The door hand/facing law the Addin's CreateDoorHandler applies, pinned against the
/// live spike's truth table (docs/REVIT_SPIKE_RESULTS.md step 3) on its two walls: W-001 drawn
/// +X (exterior = +Y = left of start→end) and W-002 drawn −X (exterior = −Y).</summary>
public sealed class DoorOrientationTests
{
    private static readonly Pt2 W1Start = new(0, 0);
    private static readonly Pt2 W1End = new(4000, 0);
    private static readonly Pt2 W2Start = new(4000, 3000);
    private static readonly Pt2 W2End = new(0, 3000);

    private static void AssertVec(double x, double y, DoorOrientation.Vec2 actual)
    {
        Assert.Equal(x, actual.X, 9);
        Assert.Equal(y, actual.Y, 9);
    }

    // Spike table rows for a family hinged at −X swinging to +Y, placed on W-001:
    //   unflipped            → hand (+1,0), facing (0,+1)  = swing L (hinge toward start), flip_facing false
    //   HandFlipped          → hand (−1,0), facing (0,+1)  = swing R
    //   FacingFlipped        → hand (+1,0), facing (0,−1)  = swing L, flip_facing true
    //   both                 → hand (−1,0), facing (0,−1)  = swing R, flip_facing true
    [Theory]
    [InlineData("L", false, 1, 0, 0, 1)]
    [InlineData("R", false, -1, 0, 0, 1)]
    [InlineData("L", true, 1, 0, 0, -1)]
    [InlineData("R", true, -1, 0, 0, -1)]
    public void Truth_table_on_w001(string swing, bool flip, double hx, double hy, double fx, double fy)
    {
        var desired = DoorOrientation.For(W1Start, W1End, swing, flip);
        AssertVec(hx, hy, desired.Hand);
        AssertVec(fx, fy, desired.Facing);
    }

    [Theory]
    [InlineData("L", false, -1, 0, 0, -1)] // hinge toward W-002's start (x=4000): hand points −X; left of −X is −Y
    [InlineData("R", false, 1, 0, 0, -1)]
    [InlineData("L", true, -1, 0, 0, 1)]
    [InlineData("R", true, 1, 0, 0, 1)]
    public void Truth_table_on_w002_drawn_minus_x(string swing, bool flip, double hx, double hy, double fx, double fy)
    {
        var desired = DoorOrientation.For(W2Start, W2End, swing, flip);
        AssertVec(hx, hy, desired.Hand);
        AssertVec(fx, fy, desired.Facing);
    }

    [Fact]
    public void Swing_only_moves_the_hand_and_flip_only_moves_the_facing()
    {
        var l = DoorOrientation.For(W1Start, W1End, "L", false);
        var lFlipped = DoorOrientation.For(W1Start, W1End, "L", true);
        var r = DoorOrientation.For(W1Start, W1End, "R", false);
        Assert.Equal(l.Hand, lFlipped.Hand);
        Assert.Equal(l.Facing, r.Facing);
        Assert.NotEqual(l.Hand, r.Hand);
        Assert.NotEqual(l.Facing, lFlipped.Facing);
    }

    [Fact]
    public void A_fresh_door_on_a_flipped_wall_needs_a_facing_flip_but_no_hand_flip()
    {
        // Revit aligns a fresh door's FacingOrientation with Wall.Orientation; on a Flipped
        // W-001 that is (0,−1) although the plan's flip_facing is falsy (leaf sweeps +Y).
        var desired = DoorOrientation.For(W1Start, W1End, "L", false);
        Assert.Equal(-1, DoorOrientation.Sign(new DoorOrientation.Vec2(0, -1), desired.Facing));
        Assert.Equal(1, DoorOrientation.Sign(new DoorOrientation.Vec2(1, 0), desired.Hand));
        // ...and after flipFacing() the instance agrees
        Assert.Equal(1, DoorOrientation.Sign(new DoorOrientation.Vec2(0, 1), desired.Facing));
    }

    [Fact]
    public void Sign_ignores_z_and_reports_perpendicular_as_zero()
    {
        var desired = DoorOrientation.For(W1Start, W1End, "L", false);
        Assert.Equal(1, DoorOrientation.Sign(new DoorOrientation.Vec2(0.7071, 0), desired.Hand));
        Assert.Equal(0, DoorOrientation.Sign(new DoorOrientation.Vec2(0, 1), desired.Hand));
        Assert.Equal(0, DoorOrientation.Sign(new DoorOrientation.Vec2(0, 0), desired.Hand));
    }

    [Fact]
    public void Skewed_wall_follows_the_same_law()
    {
        // a 45° wall: u = (√½, √½), left = (−√½, √½)
        var desired = DoorOrientation.For(new Pt2(0, 0), new Pt2(1000, 1000), "R", true);
        var s = Math.Sqrt(0.5);
        AssertVec(-s, -s, desired.Hand);
        AssertVec(s, -s, desired.Facing);
    }

    [Fact]
    public void Contract_violations_throw()
    {
        Assert.Throws<ArgumentException>(() => DoorOrientation.For(W1Start, W1Start, "L", false));
        Assert.Throws<ArgumentException>(() => DoorOrientation.For(W1Start, W1End, "left", false));
    }
}
