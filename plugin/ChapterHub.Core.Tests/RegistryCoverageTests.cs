using System.Text.Json;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>Rule 4 lockstep check: the hand-maintained C# op-args records cover exactly the
/// ops in ops/registry.json — adding or removing an op there fails this test until the C#
/// side follows.</summary>
public sealed class RegistryCoverageTests
{
    [Fact]
    public void CSharp_arg_records_cover_exactly_the_registry_ops()
    {
        using var doc = JsonDocument.Parse(
            File.ReadAllText(TestPaths.Contracts("ops", "registry.json")));
        var registryOps = doc.RootElement.GetProperty("ops").EnumerateObject()
            .Select(p => p.Name).OrderBy(n => n).ToArray();
        var csharpOps = OpArgsRegistry.ArgTypes.Keys.OrderBy(n => n).ToArray();
        Assert.Equal(registryOps, csharpOps);
    }
}
