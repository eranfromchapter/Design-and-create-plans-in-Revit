using System.Text.Json;
using System.Text.Json.Serialization;

namespace ChapterHub.Core.Contracts;

/// <summary>
/// The single serializer configuration for every contract type. Hand-maintained C# records
/// (Rule 4) map PascalCase members to the schemas' snake_case; unknown members are rejected
/// (nested additionalProperties:false); nulls are never written, so nothing is materialized
/// on serialization that was not present on parse (no-defaults rule, PLAN.md Part D).
/// </summary>
public static class ContractJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = false,
    };

    public static T Deserialize<T>(string json) =>
        JsonSerializer.Deserialize<T>(json, Options)
        ?? throw new JsonException("null document");

    public static T Deserialize<T>(JsonElement element) =>
        element.Deserialize<T>(Options) ?? throw new JsonException("null document");

    public static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Options);
}
