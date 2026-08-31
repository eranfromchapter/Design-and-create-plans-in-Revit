using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>Sim-vs-plugin placement cross-check (Phase 1 acceptance, amendment revit-6):
/// the C# side of the shared fixture. The Python twin is test_placement_conformance.py.</summary>
public sealed class PlacementConformanceTests
{
    private static JsonElement Cases() =>
        JsonDocument.Parse(File.ReadAllText(
            TestPaths.Contracts("fixtures", "placement", "manifest.json")))
            .RootElement.GetProperty("cases");

    public static TheoryData<string> CaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var c in Cases().EnumerateArray()) data.Add(c.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(CaseNames))]
    public void Placement_matches_shared_fixture(string name)
    {
        var c = Cases().EnumerateArray().Single(x => x.GetProperty("name").GetString() == name);
        var wall = c.GetProperty("wall");
        var start = wall.GetProperty("start");
        var end = wall.GetProperty("end");

        var point = Placement.Place(
            c.GetProperty("kind").GetString()!,
            new Pt2(start[0].GetDouble(), start[1].GetDouble()),
            new Pt2(end[0].GetDouble(), end[1].GetDouble()),
            wall.GetProperty("thickness_mm").GetDouble(),
            c.GetProperty("offset_mm").GetDouble(),
            c.GetProperty("z_mm").GetDouble());

        var expected = c.GetProperty("expected_point_mm");
        Assert.True(Math.Abs(point.X - expected[0].GetDouble()) < 1e-6, $"x: {point.X}");
        Assert.True(Math.Abs(point.Y - expected[1].GetDouble()) < 1e-6, $"y: {point.Y}");
        Assert.Equal(c.GetProperty("z_mm").GetDouble(), point.Z);
    }
}
