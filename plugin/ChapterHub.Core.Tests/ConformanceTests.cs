using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>Cross-language conformance: this exact suite (same manifest) runs in TS and Python too.</summary>
public sealed class ConformanceTests
{
    private static readonly Dictionary<string, RejectReason> ReasonNames = new()
    {
        ["bad_signature"] = RejectReason.BadSignature,
        ["expired_ttl"] = RejectReason.ExpiredTtl,
        ["bad_seq"] = RejectReason.BadSeq,
        ["unknown_op"] = RejectReason.UnknownOp,
        ["invalid_args"] = RejectReason.InvalidArgs,
        ["schema_invalid"] = RejectReason.SchemaInvalid,
    };

    public static TheoryData<string> CaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var c in Manifest().Cases) data.Add(c.Name);
        return data;
    }

    private sealed record ManifestCase(
        string Name, WireEnvelope Envelope, string VerifyAt, long LastCommittedSeq,
        string Expect, string? Reason);

    private sealed record ManifestDoc(
        string PublicKeyHex, string PrivateSeedHex, IReadOnlyList<ManifestCase> Cases);

    private static ManifestDoc Manifest()
    {
        var json = File.ReadAllText(TestPaths.Contracts("fixtures", "conformance", "manifest.json"));
        var options = new JsonSerializerOptions(ContractJson.Options)
        {
            UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Skip,
        };
        return JsonSerializer.Deserialize<ManifestDoc>(json, options)!;
    }

    [Theory]
    [MemberData(nameof(CaseNames))]
    public void Conformance_case_produces_expected_outcome(string name)
    {
        var manifest = Manifest();
        var c = manifest.Cases.Single(x => x.Name == name);

        var result = EnvelopeVerifier.Verify(
            c.Envelope,
            Convert.FromHexString(manifest.PublicKeyHex),
            DateTimeOffset.Parse(c.VerifyAt),
            c.LastCommittedSeq);

        Assert.Equal(c.Expect == "accepted", result.Accepted);
        if (!result.Accepted)
            Assert.Equal(ReasonNames[c.Reason!], result.Reason);
    }
}
