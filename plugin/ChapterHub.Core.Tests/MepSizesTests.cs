using ChapterHub.Core;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>Trade-size binding the Addin applies to create_pipe / create_conduit diameters
/// (live spike steps 4–5: literal mm values never bind to Revit's size tables).</summary>
public sealed class MepSizesTests
{
    // an imperial pipe segment table in mm (½" … 4")
    private static readonly double[] Imperial = [12.7, 19.05, 25.4, 31.75, 38.1, 50.8, 63.5, 76.2, 101.6];

    // Revit's EMT conduit standard (trade sizes ½" … 4")
    private static readonly double[] Emt = [12.7, 19.05, 25.4, 31.75, 38.1, 50.8, 63.5, 76.2, 88.9, 101.6];

    // metric DN table
    private static readonly double[] Metric = [15, 20, 25, 32, 40, 50, 65, 80, 100];

    [Theory]
    [InlineData(76, 76.2)] // STACK_WC_DIAMETER_MM → 3"
    [InlineData(51, 50.8)] // STACK_MIN_DIAMETER_MM → 2"
    [InlineData(38, 38.1)] // kitchen sink / tub / dishwasher drain → 1½"
    [InlineData(32, 31.75)] // lav drain → 1¼"
    [InlineData(76.2, 76.2)] // exact hit
    public void Part_g_diameters_bind_to_the_imperial_nominal(double requested, double expected) =>
        Assert.Equal(expected, MepSizes.Snap(requested, Imperial));

    [Fact]
    public void Conduit_21_binds_to_three_quarter_inch_emt() =>
        Assert.Equal(19.05, MepSizes.Snap(21, Emt));

    [Fact]
    public void Metric_tables_bind_too() =>
        Assert.Equal(50, MepSizes.Snap(51, Metric));

    [Fact]
    public void Beyond_tolerance_is_null()
    {
        Assert.Null(MepSizes.Snap(21, [12.7, 25.4]));
        Assert.Null(MepSizes.Snap(70, Imperial));
        Assert.Null(MepSizes.Snap(76 + MepSizes.SnapToleranceMm + 0.2 + 0.01, Imperial));
    }

    [Fact]
    public void Empty_table_is_null()
    {
        Assert.Null(MepSizes.Snap(76, []));
        Assert.Null(MepSizes.Nearest(76, []));
    }

    [Fact]
    public void Tie_prefers_the_smaller_nominal() =>
        Assert.Equal(20.0, MepSizes.Snap(21, [22.0, 20.0]));

    [Fact]
    public void Nearest_ignores_the_tolerance() =>
        Assert.Equal(63.5, MepSizes.Nearest(60, Imperial)); // 2½" is 3.5 mm away — no tolerance applied

    [Fact]
    public void Tolerance_cannot_reach_two_nominals_of_one_table()
    {
        Assert.Equal(2.5, MepSizes.SnapToleranceMm);
        foreach (var table in new[] { Imperial, Emt, Metric })
            for (var i = 1; i < table.Length; i++)
                Assert.True(table[i] - table[i - 1] >= 2 * MepSizes.SnapToleranceMm);
    }
}
