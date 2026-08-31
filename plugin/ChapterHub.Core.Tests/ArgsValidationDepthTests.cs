using System.Text;
using System.Text.Json;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using Xunit;

namespace ChapterHub.Core.Tests;

/// <summary>
/// Freezes a KNOWN, deliberate Phase 0 divergence (PLAN.md Part D4): the C# verifier enforces
/// strict SHAPE on op args (required members, unknown members, types, tuple arity) but not the
/// registry's VALUE constraints (ranges, enums, patterns) — those land with the op handlers in
/// Phase 1. TS and Python compile the full args_schema and reject this same envelope as
/// invalid_args. When Phase 1 adds value validation, flip this test's expectation and add a
/// range-violation vector to the shared conformance manifest.
/// </summary>
public sealed class ArgsValidationDepthTests
{
    [Fact]
    public void Value_range_violations_are_deferred_to_phase1_in_csharp()
    {
        var key = Convert.FromHexString(string.Concat(Enumerable.Repeat("f00dfeed", 8)));
        var body = """
            {"envelope_id":"0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c5d","issued_at":"2026-01-01T00:00:00Z","ops":[{"args":{"end":[4000,0],"height":50,"id":"W-001","phase":"banana","revit_type":"CHPT_Partition_92mm_PLACEHOLDER","start":[0,0]},"op":"create_wall"}],"project_id":"6f1c2a3e-9b4d-4c5e-8f70-123456789abc","seq":2,"ttl_s":600,"workstation_id":"ws-design-01"}
            """.Trim();
        var envelope = new WireEnvelope
        {
            Payload = body,
            Sig = EnvelopeVerifier.HmacHex(body, key),
        };

        var result = EnvelopeVerifier.Verify(
            envelope, key, DateTimeOffset.Parse("2026-01-01T00:05:00Z"), lastCommittedSeq: 1);

        // height=50 (< 2100) and phase="banana" violate the registry args_schema; TS/Python
        // reject invalid_args. C# accepts on shape alone until Phase 1 — frozen here so the
        // divergence is visible, deliberate, and tracked instead of latent.
        Assert.True(result.Accepted);
    }
}
