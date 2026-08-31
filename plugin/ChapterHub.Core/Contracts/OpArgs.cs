using System.Text.Json;

namespace ChapterHub.Core.Contracts;

// One strict record per allowlisted op (ops/registry.json). Strict deserialization enforces
// required members and rejects unknown ones (SI-2 shape check on the plugin side). Numeric
// RANGE checks (e.g. wall height 2100–6000) are enforced by the gateway and revit-sim via the
// registry's full JSON Schemas; the plugin's per-op handlers re-check ranges in Phase 1.

public sealed record WallFlags
{
    public bool? IsExterior { get; init; }
    public bool? IsLoadBearing { get; init; }
    public bool? IsDemising { get; init; }
    public bool? IsWetWall { get; init; }
    public int? FireRatingHr { get; init; }
}

public sealed record CreateLevelArgs
{
    public required string Name { get; init; }
    public required double Elevation { get; init; }
}

public sealed record CreateWallArgs
{
    public required string Id { get; init; }
    public required Pt2 Start { get; init; }
    public required Pt2 End { get; init; }
    public required string RevitType { get; init; }
    public required double Height { get; init; }
    public required string Phase { get; init; }
    public WallFlags? Flags { get; init; }
}

public sealed record CreateDoorArgs
{
    public required string Id { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required string RevitType { get; init; }
    public required double Width { get; init; }
    public required double Height { get; init; }
    public required string Swing { get; init; }
    public bool? FlipFacing { get; init; }
}

public sealed record CreateWindowArgs
{
    public required string Id { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required double SillHeight { get; init; }
    public required string RevitType { get; init; }
    public required double Width { get; init; }
    public required double Height { get; init; }
}

public sealed record PlaceFamilyArgs
{
    public required string Id { get; init; }
    public required string RevitFamily { get; init; }
    public required string RevitType { get; init; }
    public required Pt2 Center { get; init; }
    public required double RotationDeg { get; init; }
    public required Size2 Footprint { get; init; }
    public required string Level { get; init; }
}

public sealed record PlaceDeviceArgs
{
    public required string Id { get; init; }
    public required string Kind { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required double HeightAfl { get; init; }
}

public sealed record CreatePipeArgs
{
    public required string Id { get; init; }
    public required string System { get; init; }
    public required string PipeType { get; init; }
    public required string Level { get; init; }
    public required IReadOnlyList<Pt3> Path { get; init; }
    public required double Diameter { get; init; }
}

public sealed record CreateConduitArgs
{
    public required string Id { get; init; }
    public required string Level { get; init; }
    public required IReadOnlyList<Pt3> Path { get; init; }
    public required double Diameter { get; init; }
}

public sealed record SetParameterArgs
{
    public required string TargetId { get; init; }
    public required string Param { get; init; }
    public required JsonElement Value { get; init; }
}

public sealed record SetPhaseDemolishedArgs
{
    public required string TargetId { get; init; }
}

public sealed record DeleteElementArgs
{
    public required string TargetId { get; init; }
}

public sealed record UpdateWallArgs
{
    public required string Id { get; init; }
    public Pt2? Start { get; init; }
    public Pt2? End { get; init; }
    public double? Height { get; init; }
    public string? RevitType { get; init; }
}

public sealed record LinkPointcloudArgs
{
    public required string BlobRef { get; init; }
}

public sealed record ViewSpec
{
    public required string Name { get; init; }
    public required string Kind { get; init; }
    public required int Px { get; init; }
}

public sealed record ExportViewsArgs
{
    public required IReadOnlyList<ViewSpec> Views { get; init; }
}

public sealed record ExportParametersArgs
{
    public required IReadOnlyList<string> Categories { get; init; }
}

public sealed record VerifyDeviationArgs
{
    public required IReadOnlyList<string> WallIds { get; init; }
    public required double ToleranceMm { get; init; }
}

public sealed record VerifyModelStateArgs
{
    public required IReadOnlyList<string> ElementIds { get; init; }
}

public sealed record RunInterferenceCheckArgs
{
    public required string Scope { get; init; }
}

/// <summary>The C# side of the op allowlist: one strict args record per op in
/// ops/registry.json. Kept in lockstep by the registry-coverage unit test.</summary>
public static class OpArgsRegistry
{
    public static readonly IReadOnlyDictionary<string, Type> ArgTypes = new Dictionary<string, Type>
    {
        ["create_level"] = typeof(CreateLevelArgs),
        ["create_wall"] = typeof(CreateWallArgs),
        ["create_door"] = typeof(CreateDoorArgs),
        ["create_window"] = typeof(CreateWindowArgs),
        ["place_family"] = typeof(PlaceFamilyArgs),
        ["place_device"] = typeof(PlaceDeviceArgs),
        ["create_pipe"] = typeof(CreatePipeArgs),
        ["create_conduit"] = typeof(CreateConduitArgs),
        ["set_parameter"] = typeof(SetParameterArgs),
        ["set_phase_demolished"] = typeof(SetPhaseDemolishedArgs),
        ["delete_element"] = typeof(DeleteElementArgs),
        ["update_wall"] = typeof(UpdateWallArgs),
        ["link_pointcloud"] = typeof(LinkPointcloudArgs),
        ["export_views"] = typeof(ExportViewsArgs),
        ["export_parameters"] = typeof(ExportParametersArgs),
        ["verify_deviation"] = typeof(VerifyDeviationArgs),
        ["verify_model_state"] = typeof(VerifyModelStateArgs),
        ["run_interference_check"] = typeof(RunInterferenceCheckArgs),
    };
}
