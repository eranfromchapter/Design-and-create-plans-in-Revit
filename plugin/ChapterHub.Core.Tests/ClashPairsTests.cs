using ChapterHub.Core;
using Xunit;

namespace ChapterHub.Core.Tests;

public sealed class ClashPairsTests
{
    private static readonly Dictionary<string, long> IdMap = new() { ["W-001"] = 100, ["F-001"] = 200 };
    private static readonly (string, long)[] Delta = [("E-001", 300), ("P-001", 400)];

    [Fact]
    public void Delta_wins_then_id_map_then_revit_prefix()
    {
        Assert.Equal("E-001", ClashPairs.LogicalId(300, IdMap, Delta));
        Assert.Equal("F-001", ClashPairs.LogicalId(200, IdMap, Delta));
        Assert.Equal("revit:4711", ClashPairs.LogicalId(4711, IdMap, Delta));
    }

    [Fact]
    public void Format_and_parse_round_trip()
    {
        var message = ClashPairs.Format("E-001", "P-001");
        Assert.Equal("E-001~P-001", message);
        Assert.Equal(("E-001", "P-001"), ClashPairs.Parse(message));
        Assert.Equal(("revit:4711", "P-001"), ClashPairs.Parse("revit:4711~P-001"));
        Assert.Null(ClashPairs.Parse("no pair here"));
        Assert.Null(ClashPairs.Parse("~P-001"));
    }
}
