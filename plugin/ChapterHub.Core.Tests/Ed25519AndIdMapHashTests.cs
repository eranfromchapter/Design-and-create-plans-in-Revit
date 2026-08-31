using System.Text.Json;
using ChapterHub.Core;
using Xunit;

namespace ChapterHub.Core.Tests;

public sealed class Ed25519AndIdMapHashTests
{
    private static JsonElement Manifest() =>
        JsonDocument.Parse(File.ReadAllText(
            TestPaths.Contracts("fixtures", "conformance", "manifest.json"))).RootElement;

    [Fact]
    public void Derives_the_manifest_public_key_from_the_test_seed()
    {
        var m = Manifest();
        var seed = Convert.FromHexString(m.GetProperty("private_seed_hex").GetString()!);
        Assert.Equal(m.GetProperty("public_key_hex").GetString(), Ed25519.PublicKeyHexFromSeed(seed));
    }

    [Fact]
    public void Sign_matches_the_manifest_valid_vector()
    {
        var m = Manifest();
        var seed = Convert.FromHexString(m.GetProperty("private_seed_hex").GetString()!);
        var valid = m.GetProperty("cases").EnumerateArray()
            .Single(c => c.GetProperty("name").GetString() == "valid")
            .GetProperty("envelope");
        var payload = valid.GetProperty("payload").GetString()!;
        Assert.Equal(valid.GetProperty("sig").GetString(), Ed25519.SignHex(payload, seed));
    }

    public static TheoryData<string> IdMapCaseNames()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(
            TestPaths.Contracts("fixtures", "idmap", "hash_cases.json")));
        var data = new TheoryData<string>();
        foreach (var c in doc.RootElement.GetProperty("cases").EnumerateArray())
            data.Add(c.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(IdMapCaseNames))]
    public void Id_map_hash_matches_shared_fixture(string name)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(
            TestPaths.Contracts("fixtures", "idmap", "hash_cases.json")));
        var c = doc.RootElement.GetProperty("cases").EnumerateArray()
            .Single(x => x.GetProperty("name").GetString() == name);
        var entries = c.GetProperty("entries").EnumerateObject()
            .ToDictionary(p => p.Name, p => p.Value.GetInt64());
        Assert.Equal(c.GetProperty("expected_hash").GetString(), IdMapHash.Compute(entries));
    }
}
