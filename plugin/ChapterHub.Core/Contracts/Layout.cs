namespace ChapterHub.Core.Contracts;

// Hand-maintained records for chapter-layout.v2.3.json (Rule 4: CI-verified against the shared
// fixtures — LayoutTests fail if these drift from the schema). Enum-like fields stay strings;
// vocabulary membership is enforced by the layout validator and revit-sim, not by the plugin.

public sealed record LayoutLevels
{
    public double? FloorZ { get; init; }
    public double? CeilingZ { get; init; }
    public double? SlabToSlab { get; init; }
}

public sealed record LayoutElectrical
{
    public Pt2? Panel { get; init; }
}

public sealed record LayoutScan
{
    public required string Source { get; init; }
    public required string Capture { get; init; }
    public string? CloudRef { get; init; }
    public double? ScaleFactor { get; init; }
    public double? RmsDeviationMm { get; init; }
}

public sealed record LayoutMeta
{
    public required Guid ProjectId { get; init; }
    public required string Level { get; init; }
    public required string Units { get; init; }
    public required string Origin { get; init; }
    public required string SchemaVersion { get; init; }
    public required int BriefVersion { get; init; }
    public required string Phase { get; init; }
    public LayoutLevels? Levels { get; init; }
    public LayoutElectrical? Electrical { get; init; }
    public LayoutScan? Scan { get; init; }
}

public sealed record Wall
{
    public required string Id { get; init; }
    public required Pt2 Start { get; init; }
    public required Pt2 End { get; init; }
    public required string RevitType { get; init; }
    public required double Height { get; init; }
    public bool? IsExterior { get; init; }
    public bool? IsLoadBearing { get; init; }
    public bool? IsDemising { get; init; }
    public bool? IsWetWall { get; init; }
    public int? FireRatingHr { get; init; }
    public double? AsBuiltThickness { get; init; }
    public bool? CurvedApproximation { get; init; }
    public double? Confidence { get; init; }
    public string? Source { get; init; }
}

public sealed record Door
{
    public required string Id { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required double Width { get; init; }
    public required double Height { get; init; }
    public required string RevitType { get; init; }
    public string? Swing { get; init; }
    public bool? FlipFacing { get; init; }
    public double? Confidence { get; init; }
}

public sealed record Window
{
    public required string Id { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required double Width { get; init; }
    public required double Height { get; init; }
    public required double SillHeight { get; init; }
    public required string RevitType { get; init; }
    public double? Confidence { get; init; }
}

public sealed record Room
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Program { get; init; }
    public required IReadOnlyList<Pt2> Boundary { get; init; }
    public required IReadOnlyList<string> BoundaryWallIds { get; init; }
    public IReadOnlyList<string>? AdjacentRoomIds { get; init; }
    public bool? WetZone { get; init; }
    public double? MinAreaM2 { get; init; }
}

public sealed record FurnitureItem
{
    public required string Id { get; init; }
    public required string Kind { get; init; }
    public required string RevitFamily { get; init; }
    public required string RevitType { get; init; }
    public required Pt2 Center { get; init; }
    public required double RotationDeg { get; init; }
    public required Size2 Footprint { get; init; }
    public double? FixtureUnits { get; init; }
    public IReadOnlyList<string>? Hookups { get; init; }
    public double? ClearanceFront { get; init; }
    public bool? WallSeeking { get; init; }
}

public sealed record FurnitureGroup
{
    public required string RoomId { get; init; }
    public required IReadOnlyList<FurnitureItem> Items { get; init; }
}

public sealed record CaseworkRun
{
    public required string Id { get; init; }
    public required string HostWallId { get; init; }
    public required double Offset { get; init; }
    public required double Length { get; init; }
    public required double Depth { get; init; }
    public required double Height { get; init; }
    public required bool IsCounter { get; init; }
    public required string RevitFamily { get; init; }
    public required string RevitType { get; init; }
}

public sealed record Column
{
    public required string Id { get; init; }
    public required Pt2 Center { get; init; }
    public required Size2 Footprint { get; init; }
    public double? Confidence { get; init; }
}

public sealed record Riser
{
    public required string Id { get; init; }
    public required string Type { get; init; }
    public required Pt2 Center { get; init; }
}

public sealed record LayoutConstraints
{
    public double? CirculationMin { get; init; }
    public bool? Ada { get; init; }
    public double? OutletSpacing { get; init; }
    public IReadOnlyList<string>? StyleTags { get; init; }
}

public sealed record ChapterLayout
{
    public required LayoutMeta Meta { get; init; }
    public required IReadOnlyList<Wall> Walls { get; init; }
    public required IReadOnlyList<Door> Doors { get; init; }
    public required IReadOnlyList<Window> Windows { get; init; }
    public required IReadOnlyList<Room> Rooms { get; init; }
    public required IReadOnlyList<FurnitureGroup> Furniture { get; init; }
    public IReadOnlyList<CaseworkRun>? Casework { get; init; }
    public IReadOnlyList<Column>? Columns { get; init; }
    public IReadOnlyList<Riser>? Risers { get; init; }
    public required LayoutConstraints Constraints { get; init; }
}
