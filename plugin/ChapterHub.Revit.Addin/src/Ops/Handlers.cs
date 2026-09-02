using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Structure;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using static ChapterHub.Core.UnitConversion;
using Wall = Autodesk.Revit.DB.Wall;

namespace ChapterHub.Revit.Addin.Ops;

// The op handlers the phase gates exercise live: Phase 1 (create_level, create_wall,
// create_door, create_window, place_device), Phase 5 (place_family) and Phase 6
// (create_pipe, create_conduit, run_interference_check; place_device gains `face`).
// Every other registry op routes to NotImplementedOpHandler, which fails the envelope
// CLEANLY (rolled_back) instead of pretending — those handlers land with their phases.

internal static class Lookup
{
    public static Level LevelByName(Document doc, string name) =>
        new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
            .FirstOrDefault(l => l.Name == name)
        ?? throw new OpFailure("unknown_level", name);

    public static WallType WallTypeByName(Document doc, string name) =>
        new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<WallType>()
            .FirstOrDefault(t => t.Name == name)
        ?? throw new OpFailure("unknown_revit_type", name);

    public static FamilySymbol SymbolByTypeName(Document doc, BuiltInCategory category, string typeName)
    {
        var symbol = new FilteredElementCollector(doc)
            .OfCategory(category)
            .OfClass(typeof(FamilySymbol))
            .Cast<FamilySymbol>()
            .FirstOrDefault(s => s.Name == typeName)
            ?? throw new OpFailure("unknown_revit_type", typeName);
        if (!symbol.IsActive) symbol.Activate();
        return symbol;
    }

    /// <summary>(family, type) lookup across the categories a placeable family may live in.</summary>
    public static FamilySymbol SymbolByFamilyAndType(
        Document doc, IEnumerable<BuiltInCategory> categories, string familyName, string typeName)
    {
        foreach (var category in categories)
        {
            var symbol = new FilteredElementCollector(doc)
                .OfCategory(category)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .FirstOrDefault(s => s.FamilyName == familyName && s.Name == typeName);
            if (symbol is null) continue;
            if (!symbol.IsActive) symbol.Activate();
            return symbol;
        }
        throw new OpFailure("unknown_revit_type", $"{familyName}/{typeName}");
    }

    public static Wall HostWall(OpContext context, string logicalId) =>
        context.ResolveTarget(logicalId) as Wall
        ?? throw new OpFailure("unknown_host", logicalId);

    public static (Pt2 Start, Pt2 End) CenterlineMm(Wall wall)
    {
        var curve = (wall.Location as LocationCurve)?.Curve
            ?? throw new OpFailure("unknown_host", wall.Id.ToString());
        var p0 = curve.GetEndPoint(0);
        var p1 = curve.GetEndPoint(1);
        return (new Pt2(FtToMm(p0.X), FtToMm(p0.Y)), new Pt2(FtToMm(p1.X), FtToMm(p1.Y)));
    }

    public static XYZ Xyz(Pt3 p) => new(MmToFt(p.X), MmToFt(p.Y), MmToFt(p.Z));

    /// <summary>The connector of a pipe/conduit sitting at `point` (within 1 mm).</summary>
    public static Connector ConnectorAt(MEPCurve curve, XYZ point)
    {
        foreach (Connector connector in curve.ConnectorManager.Connectors)
            if (connector.Origin.DistanceTo(point) < MmToFt(1.0)) return connector;
        throw new OpFailure("internal", $"no connector at {point} on {curve.Id}");
    }

    /// <summary>PIN-35: the logical id maps to the FIRST segment; the remaining segments and
    /// elbows are extras grouped under a model group named "HUB {id}".</summary>
    public static void MapRun(OpContext context, string logicalId, IReadOnlyList<ElementId> created)
    {
        context.MapCreated(logicalId, created[0]);
        for (var i = 1; i < created.Count; i++) context.MapExtra(logicalId, created[i]);
        if (created.Count > 1)
        {
            var group = context.Doc.Create.NewGroup(created.ToList());
            group.GroupType.Name = $"HUB {logicalId}";
            context.MapExtra(logicalId, group.Id);
        }
    }
}

public sealed class CreateLevelHandler : IOpHandler
{
    public string Op => "create_level";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreateLevelArgs>(args);
        var level = Level.Create(context.Doc, MmToFt(a.Elevation));
        level.Name = a.Name;
        context.MapCreated(a.Name, level.Id);
    }
}

public sealed class CreateWallHandler : IOpHandler
{
    public string Op => "create_wall";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreateWallArgs>(args);
        var wallType = Lookup.WallTypeByName(context.Doc, a.RevitType);
        var level = new FilteredElementCollector(context.Doc)
            .OfClass(typeof(Level)).Cast<Level>().OrderBy(l => l.Elevation).FirstOrDefault()
            ?? throw new OpFailure("unknown_level", "no level in model");
        // D1/D4 convention: exterior/finish side = LEFT of start->end; no flip flag in v1.
        var line = Line.CreateBound(
            new XYZ(MmToFt(a.Start.X), MmToFt(a.Start.Y), level.Elevation),
            new XYZ(MmToFt(a.End.X), MmToFt(a.End.Y), level.Elevation));
        var structural = a.Flags?.IsLoadBearing ?? false;
        var wall = Wall.Create(
            context.Doc, line, wallType.Id, level.Id, MmToFt(a.Height), 0, false, structural);
        context.MapCreated(a.Id, wall.Id);
    }
}

public sealed class CreateDoorHandler : IOpHandler
{
    public string Op => "create_door";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreateDoorArgs>(args);
        var host = Lookup.HostWall(context, a.HostWallId);
        var symbol = Lookup.SymbolByTypeName(context.Doc, BuiltInCategory.OST_Doors, a.RevitType);
        var (start, end) = Lookup.CenterlineMm(host);
        var point = Placement.Place("centerline", start, end, 0, a.Offset, 0);
        var level = context.Doc.GetElement(host.LevelId) as Level
            ?? throw new OpFailure("unknown_level", a.HostWallId);
        var instance = context.Doc.Create.NewFamilyInstance(
            new XYZ(MmToFt(point.X), MmToFt(point.Y), level.Elevation),
            symbol, host, level, StructuralType.NonStructural);
        // Phase 5 swing.py convention: the leaf sweeps LEFT of start->end when flip_facing is
        // falsy; swing L|R is the hinge side seen from the swept side. Revit's hand/facing flags
        // are relative to the family's authored orientation, so the mapping below is the
        // literal one the pre-Phase-6 live spike confirms or inverts (docs/MANUAL_REVIT_TEST.md).
        if ((a.Swing == "R") != instance.HandFlipped) instance.flipHand();
        if ((a.FlipFacing ?? false) != instance.FacingFlipped) instance.flipFacing();
        context.MapCreated(a.Id, instance.Id);
    }
}

public sealed class CreateWindowHandler : IOpHandler
{
    public string Op => "create_window";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreateWindowArgs>(args);
        var host = Lookup.HostWall(context, a.HostWallId);
        var symbol = Lookup.SymbolByTypeName(context.Doc, BuiltInCategory.OST_Windows, a.RevitType);
        var (start, end) = Lookup.CenterlineMm(host);
        var point = Placement.Place("centerline", start, end, 0, a.Offset, a.SillHeight);
        var level = context.Doc.GetElement(host.LevelId) as Level
            ?? throw new OpFailure("unknown_level", a.HostWallId);
        var instance = context.Doc.Create.NewFamilyInstance(
            new XYZ(MmToFt(point.X), MmToFt(point.Y), level.Elevation + MmToFt(a.SillHeight)),
            symbol, host, level, StructuralType.NonStructural);
        context.MapCreated(a.Id, instance.Id);
    }
}

public sealed class PlaceFamilyHandler : IOpHandler
{
    public string Op => "place_family";

    private static readonly BuiltInCategory[] Categories =
    [
        BuiltInCategory.OST_Furniture,
        BuiltInCategory.OST_PlumbingFixtures,
        BuiltInCategory.OST_Casework,
        BuiltInCategory.OST_SpecialityEquipment,
        BuiltInCategory.OST_ElectricalEquipment,
    ];

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<PlaceFamilyArgs>(args);
        var level = Lookup.LevelByName(context.Doc, a.Level);
        var symbol = Lookup.SymbolByFamilyAndType(context.Doc, Categories, a.RevitFamily, a.RevitType);
        var origin = new XYZ(MmToFt(a.Center.X), MmToFt(a.Center.Y), level.Elevation);
        var instance = context.Doc.Create.NewFamilyInstance(origin, symbol, level, StructuralType.NonStructural);
        if (a.RotationDeg != 0)
        {
            // Part G: rotation_deg is CCW about +Z at the footprint centre (the sim's furniture_rect).
            var axis = Line.CreateBound(origin, origin + XYZ.BasisZ);
            ElementTransformUtils.RotateElement(context.Doc, instance.Id, axis, a.RotationDeg * Math.PI / 180.0);
        }
        context.MapCreated(a.Id, instance.Id);
    }
}

public sealed class PlaceDeviceHandler : IOpHandler
{
    public string Op => "place_device";

    private static readonly BuiltInCategory[] Categories =
    [
        BuiltInCategory.OST_ElectricalFixtures,
        BuiltInCategory.OST_LightingDevices,
    ];

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<PlaceDeviceArgs>(args);
        var types = context.Catalogs.RequireMepTypes();
        if (!types.DeviceFamilies.TryGetValue(a.Kind, out var family))
            throw new OpFailure("invalid_args", $"device kind {a.Kind}");
        var host = Lookup.HostWall(context, a.HostWallId);
        var symbol = Lookup.SymbolByFamilyAndType(context.Doc, Categories, family.RevitFamily, family.RevitType);
        var (start, end) = Lookup.CenterlineMm(host);
        // The shared placement law (fixtures/placement): left = +90° CCW of start->end, which is
        // the wall's exterior/finish side under the D1 convention; `face` names the ROOM side.
        var kind = a.Face == "right" ? "face_right" : "face_left";
        var point = Placement.Place(kind, start, end, FtToMm(host.Width), a.Offset, a.HeightAfl);
        var level = context.Doc.GetElement(host.LevelId) as Level
            ?? throw new OpFailure("unknown_level", a.HostWallId);
        var location = new XYZ(MmToFt(point.X), MmToFt(point.Y), level.Elevation + MmToFt(a.HeightAfl));
        var face = SideFaceAt(context.Doc, host, location)
            ?? throw new OpFailure("unknown_host", $"no face of {a.HostWallId} within 1 mm of the {a.Face} placement");
        var instance = context.Doc.Create.NewFamilyInstance(face, location, XYZ.BasisZ, symbol);
        context.MapCreated(a.Id, instance.Id);
    }

    /// <summary>The wall side face (interior or exterior shell) the placement point lies on.</summary>
    private static Reference? SideFaceAt(Document doc, Wall host, XYZ point)
    {
        foreach (var layer in new[] { ShellLayerType.Exterior, ShellLayerType.Interior })
        {
            foreach (var reference in HostObjectUtils.GetSideFaces(host, layer))
            {
                if (host.GetGeometryObjectFromReference(reference) is not Face face) continue;
                var projection = face.Project(point);
                if (projection is not null && projection.Distance < MmToFt(1.0)) return reference;
            }
        }
        return null;
    }
}

public sealed class CreatePipeHandler : IOpHandler
{
    public string Op => "create_pipe";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreatePipeArgs>(args);
        var types = context.Catalogs.RequireMepTypes();
        if (!types.SystemTypeNames.TryGetValue(a.System, out var systemName))
            throw new OpFailure("invalid_args", $"system {a.System}");
        if (!types.PipeTypes.Values.Contains(a.PipeType))
            throw new OpFailure("unknown_revit_type", a.PipeType); // the sim's code for the same condition
        var doc = context.Doc;
        var systemType = new FilteredElementCollector(doc).OfClass(typeof(PipingSystemType))
            .Cast<PipingSystemType>().FirstOrDefault(t => t.Name == systemName)
            ?? throw new OpFailure("unknown_system_type", systemName);
        var pipeType = new FilteredElementCollector(doc).OfClass(typeof(PipeType))
            .Cast<PipeType>().FirstOrDefault(t => t.Name == a.PipeType)
            ?? throw new OpFailure("unknown_revit_type", a.PipeType);
        var level = Lookup.LevelByName(doc, a.Level);
        var path = Classify(a.Path);

        var created = new List<ElementId>();
        var pipes = new List<Pipe>();
        for (var i = 1; i < path.Points.Count; i++)
        {
            var pipe = Pipe.Create(doc, systemType.Id, pipeType.Id, level.Id,
                Lookup.Xyz(path.Points[i - 1]), Lookup.Xyz(path.Points[i]));
            pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)?.Set(MmToFt(a.Diameter));
            pipes.Add(pipe);
            created.Add(pipe.Id);
        }
        for (var i = 1; i < pipes.Count; i++)
        {
            var joint = Lookup.Xyz(path.Points[i]);
            var elbow = doc.Create.NewElbowFitting(
                Lookup.ConnectorAt(pipes[i - 1], joint), Lookup.ConnectorAt(pipes[i], joint));
            created.Add(elbow.Id);
        }
        Lookup.MapRun(context, a.Id, created);
    }

    internal static PipePath.Classification Classify(IReadOnlyList<Pt3> path)
    {
        try
        {
            return PipePath.Classify(path);
        }
        catch (PipePathError error)
        {
            // sim parity: a degenerate segment is `invalid_path` there; fittings keep their code
            throw new OpFailure(error.Code == "zero_length" ? "invalid_path" : error.Code, error.Message);
        }
    }
}

public sealed class CreateConduitHandler : IOpHandler
{
    public string Op => "create_conduit";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<CreateConduitArgs>(args);
        var types = context.Catalogs.RequireMepTypes();
        var doc = context.Doc;
        var conduitType = new FilteredElementCollector(doc).OfClass(typeof(ConduitType))
            .Cast<ConduitType>().FirstOrDefault(t => t.Name == types.ConduitType)
            ?? throw new OpFailure("unknown_revit_type", types.ConduitType);
        var level = Lookup.LevelByName(doc, a.Level);
        var path = CreatePipeHandler.Classify(a.Path);

        var created = new List<ElementId>();
        var conduits = new List<Conduit>();
        for (var i = 1; i < path.Points.Count; i++)
        {
            var conduit = Conduit.Create(doc, conduitType.Id,
                Lookup.Xyz(path.Points[i - 1]), Lookup.Xyz(path.Points[i]), level.Id);
            conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)?.Set(MmToFt(a.Diameter));
            conduits.Add(conduit);
            created.Add(conduit.Id);
        }
        for (var i = 1; i < conduits.Count; i++)
        {
            var joint = Lookup.Xyz(path.Points[i]);
            var elbow = doc.Create.NewElbowFitting(
                Lookup.ConnectorAt(conduits[i - 1], joint), Lookup.ConnectorAt(conduits[i], joint));
            created.Add(elbow.Id);
        }
        Lookup.MapRun(context, a.Id, created);
    }
}

/// <summary>The plugin's executor of the ONE clash law (PLAN.md Part G): after a regenerate,
/// every element THIS envelope created is intersected (ElementIntersectsElementFilter) with
/// every created or id-mapped element; walls/doors/windows/levels are never clash elements;
/// exempt category pairs come from clash_prisms.json (ClashExemptions); connector-joined pairs
/// and elements sharing a logical id (segments of one run) are skipped. The first hit fails
/// the envelope with `interference "A~B"` in logical ids — the merge gate's Phase B signal.</summary>
public sealed class RunInterferenceCheckHandler : IOpHandler
{
    public string Op => "run_interference_check";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<RunInterferenceCheckArgs>(args);
        if (a.Scope != "last_commit") throw new OpFailure("invalid_args", $"scope {a.Scope}");
        var doc = context.Doc;
        var exemptions = context.Catalogs.RequireClash();
        var types = context.Catalogs.MepTypes;
        doc.Regenerate();

        var created = context.Created();
        if (created.Count == 0) return;
        // created × ALL: every clash-class element in the document is a candidate — modelled
        // columns, existing MEP and hand-placed families included (reported as
        // revit:<ElementId> when the HUB never created them); walls/doors/windows never are
        var clashCategories = new ElementMulticategoryFilter(new List<BuiltInCategory>
        {
            BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_FlexPipeCurves,
            BuiltInCategory.OST_Conduit, BuiltInCategory.OST_ConduitFitting,
            BuiltInCategory.OST_ElectricalFixtures, BuiltInCategory.OST_LightingDevices,
            BuiltInCategory.OST_Furniture, BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Casework,
            BuiltInCategory.OST_SpecialityEquipment, BuiltInCategory.OST_ElectricalEquipment,
            BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_StructuralFraming,
        });

        foreach (var (aLogical, aElementId) in created)
        {
            if (doc.GetElement(new ElementId(aElementId)) is not { } element) continue;
            var aClass = ClashClass(element);
            if (aClass is null) continue;
            var hits = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType()
                .WherePasses(clashCategories)
                .WherePasses(new ElementIntersectsElementFilter(element))
                .ToElements();
            foreach (var other in hits.OrderBy(e => e.Id.Value))
            {
                var bLogical = context.LogicalIdOf(other.Id);
                if (bLogical == aLogical) continue; // segments/fittings of one run
                var bClass = ClashClass(other);
                if (bClass is null) continue;
                if (exemptions.IsExempt(aClass, SystemOf(element, types), bClass, SystemOf(other, types))) continue;
                if (ConnectorJoined(element, other)) continue;
                throw new OpFailure("interference", ClashPairs.Format(aLogical, bLogical));
            }
        }
    }

    /// <summary>Category → clash class; null = not a clash element (walls, doors, windows,
    /// levels, rooms, anything unknown).</summary>
    internal static string? ClashClass(Element element)
    {
        if (element.Category is null) return null;
        return (BuiltInCategory)element.Category.Id.Value switch
        {
            BuiltInCategory.OST_PipeCurves or BuiltInCategory.OST_PipeFitting
                or BuiltInCategory.OST_FlexPipeCurves => "pipe",
            BuiltInCategory.OST_Conduit or BuiltInCategory.OST_ConduitFitting => "conduit",
            BuiltInCategory.OST_ElectricalFixtures or BuiltInCategory.OST_LightingDevices => "device",
            BuiltInCategory.OST_Furniture or BuiltInCategory.OST_PlumbingFixtures
                or BuiltInCategory.OST_Casework or BuiltInCategory.OST_SpecialityEquipment
                or BuiltInCategory.OST_ElectricalEquipment => "furniture",
            BuiltInCategory.OST_Columns or BuiltInCategory.OST_StructuralColumns
                or BuiltInCategory.OST_StructuralFraming => "structure",
            _ => null,
        };
    }

    private static string? SystemOf(Element element, MepTypes? types)
    {
        var name = element.get_Parameter(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)?.AsValueString();
        return name is null ? null : types?.SystemOf(name) ?? name;
    }

    private static bool ConnectorJoined(Element a, Element b)
    {
        var managerA = Connectors(a);
        var managerB = Connectors(b);
        if (managerA is null || managerB is null) return false;
        foreach (Connector ca in managerA.Connectors)
            foreach (Connector cb in managerB.Connectors)
                if (ca.IsConnectedTo(cb)) return true;
        return false;
    }

    private static ConnectorManager? Connectors(Element element) => element switch
    {
        MEPCurve curve => curve.ConnectorManager,
        FamilyInstance instance => instance.MEPModel?.ConnectorManager,
        _ => null,
    };
}

public sealed class NotImplementedOpHandler(string op) : IOpHandler
{
    public string Op { get; } = op;

    public void Execute(OpContext context, JsonElement args) =>
        throw new OpFailure("op_not_implemented", $"{Op} lands with its phase (see registry)");
}

public static class OpHandlerRegistry
{
    public static IReadOnlyDictionary<string, IOpHandler> Build()
    {
        var handlers = new List<IOpHandler>
        {
            new CreateLevelHandler(),
            new CreateWallHandler(),
            new CreateDoorHandler(),
            new CreateWindowHandler(),
            new PlaceFamilyHandler(),
            new PlaceDeviceHandler(),
            new CreatePipeHandler(),
            new CreateConduitHandler(),
            new RunInterferenceCheckHandler(),
        };
        var map = handlers.ToDictionary(h => h.Op);
        foreach (var op in OpArgsRegistry.ArgTypes.Keys)
            if (!map.ContainsKey(op)) map[op] = new NotImplementedOpHandler(op);
        return map;
    }
}
