using ChapterHub.Core;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>The shared clash table (catalogs/clash_prisms.json) as the executor applies it —
/// the same verdicts revit-sim's tests pin (tools/revit-sim/tests/test_clash_law.py):
/// pipe/pipe only within one system, conduit/conduit, device/device, device/conduit,
/// furniture/device, furniture/conduit exempt; pipe/furniture STRICT here (the
/// served-fixture rule is only resolvable in the merge gate); everything else clashes.</summary>
public sealed class ClashExemptionsTests
{
    private static readonly ClashExemptions Table = ClashExemptions.FromJson(
        File.ReadAllText(TestPaths.Contracts("catalogs", "clash_prisms.json")));

    [Fact]
    public void Rules_are_the_seven_shared_pairs()
    {
        Assert.Equal(
            [
                ("pipe", "pipe", "same_system"),
                ("conduit", "conduit", null),
                ("device", "device", null),
                ("device", "conduit", null),
                ("pipe", "furniture", "pipe_serves_fixture"),
                ("furniture", "device", null),
                ("furniture", "conduit", null),
            ],
            Table.Rules.Select(r => (r.A, r.B, r.When)).ToArray());
    }

    [Theory]
    [InlineData("pipe", "sanitary", "pipe", "sanitary", true)]
    [InlineData("pipe", "sanitary", "pipe", "vent", false)]
    [InlineData("pipe", null, "pipe", null, false)]
    [InlineData("conduit", null, "conduit", null, true)]
    [InlineData("device", null, "device", null, true)]
    [InlineData("device", null, "conduit", null, true)]
    [InlineData("conduit", null, "device", null, true)]
    [InlineData("pipe", "sanitary", "furniture", null, false)]
    [InlineData("furniture", null, "pipe", "sanitary", false)]
    [InlineData("furniture", null, "device", null, true)]
    [InlineData("furniture", null, "conduit", null, true)]
    [InlineData("furniture", null, "furniture", null, false)]
    [InlineData("structure", null, "pipe", "sanitary", false)]
    [InlineData("structure", null, "furniture", null, false)]
    [InlineData("pipe", "sanitary", "conduit", null, false)]
    [InlineData("pipe", "sanitary", "device", null, false)]
    public void Exemption_verdicts_match_the_sim(string a, string? sa, string b, string? sb, bool exempt)
    {
        Assert.Equal(exempt, Table.IsExempt(a, sa, b, sb));
        Assert.Equal(exempt, Table.IsExempt(b, sb, a, sa)); // symmetric
    }

    [Fact]
    public void Priorities_follow_part_g()
    {
        Assert.Equal(0, Table.Priority("structure", null));
        Assert.Equal(1, Table.Priority("pipe", "sanitary"));
        Assert.Equal(1, Table.Priority("pipe", "vent"));
        Assert.Equal(2, Table.Priority("pipe", "supply_h"));
        Assert.Equal(4, Table.Priority("conduit", null));
        Assert.Equal(4, Table.Priority("device", null));
        Assert.Equal(5, Table.Priority("furniture", null));
    }

    [Fact]
    public void Mep_types_catalog_parses_and_reverses_system_names()
    {
        var types = MepTypes.FromJson(File.ReadAllText(TestPaths.Contracts("catalogs", "mep_types.json")));
        Assert.Equal(["gfci", "receptacle", "receptacle_240", "switch"], types.DeviceFamilies.Keys.OrderBy(k => k).ToArray());
        Assert.Equal("sanitary", types.SystemOf(types.SystemTypeNames["sanitary"]));
        Assert.Null(types.SystemOf("Fire Protection"));
        Assert.Equal(21.0, types.ConduitDiameterMm);
        Assert.EndsWith("_PLACEHOLDER", types.ConduitType); // human input outstanding (Part J)
    }
}
