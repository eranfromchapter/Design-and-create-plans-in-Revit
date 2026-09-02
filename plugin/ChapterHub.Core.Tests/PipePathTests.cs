using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>C#/Python pipe-path conformance (Phase 6): the shared fixture
/// packages/contracts/fixtures/pipepath/manifest.json; the Python twin is
/// services/layout-compiler/tests/test_fittings_conformance.py.</summary>
public sealed class PipePathTests
{
    private static JsonElement Root() =>
        JsonDocument.Parse(File.ReadAllText(
            TestPaths.Contracts("fixtures", "pipepath", "manifest.json"))).RootElement;

    public static TheoryData<string> CaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var c in Root().GetProperty("cases").EnumerateArray())
            data.Add(c.GetProperty("name").GetString()!);
        return data;
    }

    [Fact]
    public void Tolerances_are_the_manifest_constants()
    {
        var root = Root();
        Assert.Equal(PipePath.AngleToleranceDeg, root.GetProperty("angle_tolerance_deg").GetDouble());
        Assert.Equal(PipePath.CollinearToleranceDeg, root.GetProperty("collinear_tolerance_deg").GetDouble());
        Assert.Equal(PipePath.MinSegmentMm, root.GetProperty("min_segment_mm").GetDouble());
    }

    [Theory]
    [MemberData(nameof(CaseNames))]
    public void Classification_matches_shared_fixture(string name)
    {
        var c = Root().GetProperty("cases").EnumerateArray()
            .Single(x => x.GetProperty("name").GetString() == name);
        var path = c.GetProperty("path").EnumerateArray()
            .Select(p => new Pt3(p[0].GetDouble(), p[1].GetDouble(), p[2].GetDouble()))
            .ToArray();
        var expect = c.GetProperty("expect");
        if (expect.GetProperty("ok").GetBoolean())
        {
            var result = PipePath.Classify(path);
            Assert.Equal(expect.GetProperty("segments").GetInt32(), result.Segments);
            Assert.Equal(
                expect.GetProperty("bends_deg").EnumerateArray().Select(b => b.GetInt32()).ToArray(),
                result.BendsDeg.ToArray());
        }
        else
        {
            var error = Assert.Throws<PipePathError>(() => PipePath.Classify(path));
            Assert.Equal(expect.GetProperty("error").GetString(), error.Code);
        }
    }
}
