using System.Text.Json;
using System.Text.Json.Nodes;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

public sealed class LayoutTests
{
    private static string FixtureJson() =>
        File.ReadAllText(Path.Combine(TestPaths.RepoRoot, "fixtures", "layouts", "minimal.json"));

    [Fact]
    public void Minimal_fixture_deserializes_strictly()
    {
        var layout = ContractJson.Deserialize<ChapterLayout>(FixtureJson());
        Assert.Equal("2.3", layout.Meta.SchemaVersion);
        Assert.Equal(4, layout.Walls.Count);
        Assert.Equal(new Pt2(0, 0), layout.Walls[0].Start);
        Assert.Equal(new Size2(2200, 900), layout.Furniture[0].Items[0].Footprint);
    }

    [Fact]
    public void Round_trip_is_semantically_identical_and_materializes_nothing()
    {
        var raw = FixtureJson();
        var layout = ContractJson.Deserialize<ChapterLayout>(raw);
        var reserialized = ContractJson.Serialize(layout);
        Assert.True(
            JsonNode.DeepEquals(JsonNode.Parse(raw), JsonNode.Parse(reserialized)),
            "re-serialized layout differs from the source document");
    }

    [Fact]
    public void Unknown_member_is_rejected()
    {
        var bad = FixtureJson().Replace("\"height\": 2700,", "\"height\": 2700, \"is_load_baering\": true,");
        Assert.Contains("is_load_baering", bad);
        Assert.Throws<JsonException>(() => ContractJson.Deserialize<ChapterLayout>(bad));
    }

    [Fact]
    public void Zero_footprint_is_rejected()
    {
        var bad = FixtureJson().Replace("[2200, 900]", "[2200, 0]");
        Assert.Throws<JsonException>(() => ContractJson.Deserialize<ChapterLayout>(bad));
    }
}
