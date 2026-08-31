using System.Text.Json;

namespace ChapterHub.Core.Contracts;

/// <summary>Wire format per command-envelope.v1.json: the gateway serializes the body once;
/// verifiers HMAC the received payload bytes verbatim before any parsing.</summary>
public sealed record WireEnvelope
{
    public required string Payload { get; init; }
    public required string Sig { get; init; }
}

public sealed record ApprovalRef
{
    public required Guid ReviewId { get; init; }
    public required string ContentHash { get; init; }
}

public sealed record OpCall
{
    public required string Op { get; init; }
    public required JsonElement Args { get; init; }
}

public sealed record EnvelopeBody
{
    public required Guid EnvelopeId { get; init; }
    public required Guid ProjectId { get; init; }
    public required string WorkstationId { get; init; }
    public required long Seq { get; init; }
    public required string IssuedAt { get; init; }
    public required int TtlS { get; init; }
    public string? CommitLabel { get; init; }
    public ApprovalRef? ApprovalRef { get; init; }
    public required IReadOnlyList<OpCall> Ops { get; init; }
}
