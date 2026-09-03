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
// create_door, create_window, place_device), Phase 5 (place_family), Phase 6
// (create_pipe, create_conduit, run_interference_check; place_device gains `face`) and
// Phase 7 (export_views, set_parameter). Every other registry op routes to
// NotImplementedOpHandler, which fails the envelope CLEANLY (rolled_back) instead of
// pretending — those handlers land with their phases.

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
        if (instance.Host is not { } doorHost || doorHost.Id != host.Id)
            throw new OpFailure("unhosted", $"{a.Id}: not hosted by {a.HostWallId}");
        // Phase 5 swing.py law: hinge at offset - w/2 (toward start) for swing L, + w/2 for R;
        // the leaf sweeps LEFT of start->end when flip_facing is falsy. Revit's HandFlipped /
        // FacingFlipped are relative to the family's authoring and to Wall.Orientation (a fresh
        // door faces the wall's exterior, which Wall.Flipped negates), so the flags are never
        // read: the placed instance's orientation VECTORS are compared with the desired world
        // directions (live spike 2026-09-03, docs/REVIT_SPIKE_RESULTS.md step 3). Assumes the
        // Door.rft authoring convention — hinge at the family's -X jamb, swing to family +Y —
        // which stage 2 of the spike verifies against Chapter's real door family.
        var desired = DoorOrientation.For(start, end, a.Swing, a.FlipFacing ?? false);
        var flipped = false;
        if (DoorOrientation.Sign(Vec(instance.HandOrientation), desired.Hand) < 0) flipped |= instance.flipHand();
        if (DoorOrientation.Sign(Vec(instance.FacingOrientation), desired.Facing) < 0) flipped |= instance.flipFacing();
        if (flipped) context.Doc.Regenerate();
        var hand = DoorOrientation.Sign(Vec(instance.HandOrientation), desired.Hand);
        var facing = DoorOrientation.Sign(Vec(instance.FacingOrientation), desired.Facing);
        if (hand <= 0 || facing <= 0)
            throw new OpFailure("door_flip_failed", $"{a.Id}: hand {hand} facing {facing} after flips");
        context.MapCreated(a.Id, instance.Id);
    }

    private static DoorOrientation.Vec2 Vec(XYZ v) => new(v.X, v.Y);
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
        // the wall's exterior/finish side under the D1 convention (confirmed live, spike step 1);
        // `face` names the ROOM side. The face is chosen GEOMETRICALLY — by its outward normal and
        // by lying within 1 mm of the law's point — never by shell layer, so Wall.Flipped (which
        // swaps Exterior/Interior against the draw direction) cannot move a device.
        var kind = a.Face == "right" ? "face_right" : "face_left";
        var point = Placement.Place(kind, start, end, FtToMm(host.Width), a.Offset, a.HeightAfl);
        var level = context.Doc.GetElement(host.LevelId) as Level
            ?? throw new OpFailure("unknown_level", a.HostWallId);
        var location = new XYZ(MmToFt(point.X), MmToFt(point.Y), level.Elevation + MmToFt(a.HeightAfl));
        var (face, sideSeen) = SideFaceOn(host, location, OutwardNormal(start, end, a.Face));
        if (face is null)
            throw new OpFailure("unknown_host", sideSeen
                ? $"{a.Id}: no face of {a.HostWallId} within 1 mm of the {a.Face} placement (host Location Line off the centerline?)"
                : $"{a.Id}: {a.HostWallId} has no side face on its {a.Face} side");
        var instance = context.Doc.Create.NewFamilyInstance(face, location, XYZ.BasisZ, symbol);
        // spike cross-cutting finding 1: a placement can "succeed" unhosted at z=0 — never commit one
        if (instance.Host is not { } deviceHost || deviceHost.Id != host.Id || instance.HostFace is null)
            throw new OpFailure("unhosted", $"{a.Id}: not face-hosted by {a.HostWallId}");
        context.MapCreated(a.Id, instance.Id);
    }

    private static XYZ OutwardNormal(Pt2 start, Pt2 end, string face)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var length = Math.Sqrt(dx * dx + dy * dy);
        var left = new XYZ(-dy / length, dx / length, 0);
        return face == "right" ? -left : left;
    }

    /// <summary>The wall side face (either shell) whose outward normal points along `outward`
    /// and which lies within 1 mm of `point`; SideSeen reports whether ANY face on that side
    /// exists (distinguishes an off-centre Location Line from a missing side).</summary>
    private static (Reference? Face, bool SideSeen) SideFaceOn(Wall host, XYZ point, XYZ outward)
    {
        var sideSeen = false;
        foreach (var layer in new[] { ShellLayerType.Exterior, ShellLayerType.Interior })
        {
            foreach (var reference in HostObjectUtils.GetSideFaces(host, layer))
            {
                if (host.GetGeometryObjectFromReference(reference) is not Face face) continue;
                var projection = face.Project(point);
                if (projection is null) continue;
                if (face.ComputeNormal(projection.UVPoint).DotProduct(outward) < 0.5) continue;
                sideSeen = true;
                if (projection.Distance < MmToFt(1.0)) return (reference, true);
            }
        }
        return (null, sideSeen);
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
        var preferences = pipeType.RoutingPreferenceManager;
        // live spike steps 4/7: a pipe type without an elbow rule makes NewElbowFitting fail
        // ("failed to insert elbow") — a template prerequisite, checked before anything is created
        if (path.Segments > 1 && preferences.GetNumberOfRules(RoutingPreferenceRuleGroupType.Elbows) == 0)
            throw new OpFailure("routing_preference_missing", $"{pipeType.Name}: no elbow in its routing preferences");
        var diameter = Fittings.BindSize(a.Id, a.Diameter, PipeNominalsMm(doc, preferences), pipeType.Name);

        var created = new List<ElementId>();
        var pipes = new List<Pipe>();
        for (var i = 1; i < path.Points.Count; i++)
        {
            var pipe = Pipe.Create(doc, systemType.Id, pipeType.Id, level.Id,
                Lookup.Xyz(path.Points[i - 1]), Lookup.Xyz(path.Points[i]));
            pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)?.Set(MmToFt(diameter));
            pipes.Add(pipe);
            created.Add(pipe.Id);
        }
        for (var i = 1; i < pipes.Count; i++)
            created.Add(Fittings.Elbow(doc, a.Id, pipes[i - 1], pipes[i], Lookup.Xyz(path.Points[i])).Id);
        Lookup.MapRun(context, a.Id, created);
    }

    /// <summary>Nominal diameters (mm) of every segment the type's routing preferences carry.</summary>
    private static IEnumerable<double> PipeNominalsMm(Document doc, RoutingPreferenceManager preferences)
    {
        var count = preferences.GetNumberOfRules(RoutingPreferenceRuleGroupType.Segments);
        var seen = new HashSet<double>();
        for (var i = 0; i < count; i++)
        {
            var rule = preferences.GetRule(RoutingPreferenceRuleGroupType.Segments, i);
            if (doc.GetElement(rule.MEPPartId) is not PipeSegment segment) continue;
            foreach (var size in segment.GetSizes())
                if (seen.Add(size.NominalDiameter)) yield return FtToMm(size.NominalDiameter);
        }
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
        // conduit types carry their fittings as type properties (spike step 7: Bend = the elbow)
        if (path.Segments > 1 && conduitType.Elbow is null)
            throw new OpFailure("routing_preference_missing", $"{conduitType.Name}: no elbow (Bend) fitting on the conduit type");
        var diameter = Fittings.BindSize(a.Id, a.Diameter, ConduitNominalsMm(doc, conduitType), conduitType.Name);

        var created = new List<ElementId>();
        var conduits = new List<Conduit>();
        for (var i = 1; i < path.Points.Count; i++)
        {
            var conduit = Conduit.Create(doc, conduitType.Id,
                Lookup.Xyz(path.Points[i - 1]), Lookup.Xyz(path.Points[i]), level.Id);
            conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)?.Set(MmToFt(diameter));
            conduits.Add(conduit);
            created.Add(conduit.Id);
        }
        for (var i = 1; i < conduits.Count; i++)
            created.Add(Fittings.Elbow(doc, a.Id, conduits[i - 1], conduits[i], Lookup.Xyz(path.Points[i])).Id);
        Lookup.MapRun(context, a.Id, created);
    }

    /// <summary>Trade sizes (mm) of the conduit standard the type is set to (e.g. EMT).</summary>
    private static IEnumerable<double> ConduitNominalsMm(Document doc, ConduitType conduitType)
    {
        var standard = conduitType.get_Parameter(BuiltInParameter.CONDUIT_STANDARD_TYPE_PARAM)?.AsValueString();
        if (string.IsNullOrEmpty(standard)) yield break;
        foreach (var entry in ConduitSizeSettings.GetConduitSizeSettings(doc))
        {
            if (entry.Key != standard) continue;
            foreach (var size in entry.Value) yield return FtToMm(size.NominalDiameter);
        }
    }
}

/// <summary>Shared by the pipe and conduit handlers: trade-size binding and guarded elbow
/// insertion (live spike steps 4–5, docs/REVIT_SPIKE_RESULTS.md).</summary>
internal static class Fittings
{
    /// <summary>The diameter actually written: the size-table nominal nearest the request when
    /// the type exposes a table (a literal 76 mm never binds OD/ID — Revit needs the table's
    /// 76.2 = 3"), the literal request when the type has no table at all; `unknown_size` when
    /// the table has nothing within MepSizes.SnapToleranceMm.</summary>
    public static double BindSize(string id, double requestedMm, IEnumerable<double> nominalsMm, string typeName)
    {
        var table = nominalsMm.ToList();
        if (table.Count == 0) return requestedMm;
        return MepSizes.Snap(requestedMm, table)
            ?? throw new OpFailure("unknown_size",
                $"{id}: {requestedMm} mm is not a size of {typeName} (nearest {MepSizes.Nearest(requestedMm, table):0.##} mm)");
    }

    /// <summary>NewElbowFitting with Revit's refusal surfaced as `fitting_insert_failed` (the
    /// routing preferences name a fitting Revit cannot place here) instead of `internal`.</summary>
    public static FamilyInstance Elbow(Document doc, string id, MEPCurve first, MEPCurve second, XYZ joint)
    {
        try
        {
            return doc.Create.NewElbowFitting(Lookup.ConnectorAt(first, joint), Lookup.ConnectorAt(second, joint));
        }
        catch (Autodesk.Revit.Exceptions.ApplicationException ex)
        {
            throw new OpFailure("fitting_insert_failed", $"{id}: {ex.Message}");
        }
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

/// <summary>Phase 7 export (docs/PHASE7_DESIGN.md §3.6, P7-12): per views[] entry a temporary
/// view in its own transaction (plan: ViewPlan on the first mapped wall's level; section: an
/// elevation through the framed model's centre looking +Y — the sim's render_section law;
/// 3d_hidden: an isometric View3D), all hidden-line, exported to PNG at `px` (fit
/// horizontally), hashed (BlobRef), PUT to the gateway, the view deleted, and ONE
/// export_ready per entry emitted after the commit_result — in views order, name never on
/// the wire. Nothing enters the id-map (the model is unchanged). Failures roll the envelope
/// back: view_export_failed, blob_upload_failed.</summary>
public sealed class ExportViewsHandler : IOpHandler
{
    public string Op => "export_views";

    public bool NeedsOwnTransactions => true;

    private const double FrameMarginMm = 250.0;
    private const double MinHalfExtentMm = 500.0;

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<ExportViewsArgs>(args);
        IReadOnlyList<ExportPlan.Frame> frames;
        try
        {
            frames = ExportPlan.From(a);
        }
        catch (ArgumentException ex)
        {
            throw new OpFailure("invalid_args", ex.Message);
        }
        var envelope = context.Envelope ?? throw new OpFailure("internal", "export_views needs the envelope context");
        var doc = context.Doc;
        var (box, level) = FrameOf(context);
        var tempDir = Path.Combine(Path.GetTempPath(), "ChapterHub", envelope.EnvelopeId.ToString());
        Directory.CreateDirectory(tempDir);
        var refs = new List<string>(frames.Count);
        try
        {
            foreach (var frame in frames)
            {
                ElementId viewId;
                using (var create = new Transaction(doc, $"HUB export {frame.Index}"))
                {
                    create.Start();
                    try
                    {
                        viewId = CreateTemporaryView(doc, frame, box, level);
                    }
                    catch (Autodesk.Revit.Exceptions.ApplicationException ex)
                    {
                        // e.g. a view type whose default template owns the display style
                        create.RollBack();
                        throw new OpFailure("view_export_failed", $"{frame.Name}: {ex.Message}");
                    }
                    create.Commit();
                }
                byte[] png;
                try
                {
                    png = ExportPng(doc, viewId, frame, tempDir);
                }
                finally
                {
                    // the temporary view never survives the envelope, success or failure
                    using var cleanup = new Transaction(doc, $"HUB export cleanup {frame.Index}");
                    cleanup.Start();
                    doc.Delete(viewId);
                    cleanup.Commit();
                }
                var blobRef = BlobRef.Of(png);
                if (!context.Uploader.Put(envelope.ProjectId.ToString(), blobRef, png, out var error))
                    throw new OpFailure("blob_upload_failed", $"{frame.Name}: {error}");
                refs.Add(blobRef);
            }
        }
        finally
        {
            try
            {
                Directory.Delete(tempDir, recursive: true);
            }
            catch (Exception)
            {
                // best effort: a locked or access-denied temp file must not fail an export
                // whose blobs are already stored
            }
        }
        foreach (var blobRef in refs) context.Emit(ExportPlan.ReadyMessage(blobRef));
    }

    /// <summary>The union bounding box of everything the HUB created (fallback: every wall) and
    /// the level the plan view is drawn on (the first mapped wall's, else the first level).</summary>
    private static (BoundingBoxXYZ Box, Level Level) FrameOf(OpContext context)
    {
        var doc = context.Doc;
        BoundingBoxXYZ? union = null;
        Level? level = null;
        foreach (var entry in context.Store.Entries)
        {
            var element = doc.GetElement(new ElementId(entry.Value));
            if (element is null) continue;
            if (level is null && element is Wall wall) level = doc.GetElement(wall.LevelId) as Level;
            union = Union(union, element.get_BoundingBox(null));
        }
        if (union is null)
        {
            foreach (var wall in new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Wall>())
            {
                level ??= doc.GetElement(wall.LevelId) as Level;
                union = Union(union, wall.get_BoundingBox(null));
            }
        }
        level ??= new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().FirstOrDefault()
            ?? throw new OpFailure("unknown_level", "no level in model");
        if (union is null) throw new OpFailure("view_export_failed", "nothing to frame: no walls with geometry");
        return (union, level);
    }

    private static BoundingBoxXYZ? Union(BoundingBoxXYZ? a, BoundingBoxXYZ? b)
    {
        if (b is null) return a;
        if (a is null) return new BoundingBoxXYZ { Min = b.Min, Max = b.Max };
        return new BoundingBoxXYZ
        {
            Min = new XYZ(Math.Min(a.Min.X, b.Min.X), Math.Min(a.Min.Y, b.Min.Y), Math.Min(a.Min.Z, b.Min.Z)),
            Max = new XYZ(Math.Max(a.Max.X, b.Max.X), Math.Max(a.Max.Y, b.Max.Y), Math.Max(a.Max.Z, b.Max.Z)),
        };
    }

    /// <summary>A view family type of the family, preferring one WITHOUT a default view
    /// template (a template that owns Model Display would refuse DisplayStyle.HLR).</summary>
    private static ElementId ViewFamilyTypeId(Document doc, ViewFamily family) =>
        new FilteredElementCollector(doc).OfClass(typeof(ViewFamilyType)).Cast<ViewFamilyType>()
            .Where(t => t.ViewFamily == family)
            .OrderBy(t => t.DefaultTemplateId == ElementId.InvalidElementId ? 0 : 1)
            .FirstOrDefault()?.Id
        ?? throw new OpFailure("view_export_failed", $"the model has no {family} view family type");

    private static ElementId CreateTemporaryView(Document doc, ExportPlan.Frame frame, BoundingBoxXYZ box, Level level)
    {
        View view;
        switch (frame.Kind)
        {
            case "plan":
                view = ViewPlan.Create(doc, ViewFamilyTypeId(doc, ViewFamily.FloorPlan), level.Id);
                break;
            case "section":
            {
                // an elevation through the framed centre looking +Y (the sim's render_section law):
                // ViewSection.CreateSection reads the VIEW DIRECTION from Transform.BasisZ and up
                // from BasisY, computes the right-hand direction itself so (right, up, view) is
                // left-handed (right = +X here: x grows to the right of the image, as in the sim),
                // crops to the Min/Max projection on the cut plane and sets the far clip to
                // Max.Z - Min.Z — so Min.Z = 0 is the cut and Max.Z reaches past the model
                var centre = (box.Min + box.Max) / 2.0;
                var halfWidth = Math.Max((box.Max.X - box.Min.X) / 2.0 + MmToFt(FrameMarginMm), MmToFt(MinHalfExtentMm));
                var halfHeight = Math.Max((box.Max.Z - box.Min.Z) / 2.0 + MmToFt(FrameMarginMm), MmToFt(MinHalfExtentMm));
                var depth = Math.Max((box.Max.Y - box.Min.Y) / 2.0 + MmToFt(FrameMarginMm), MmToFt(MinHalfExtentMm));
                var transform = Transform.Identity;
                transform.Origin = centre;
                transform.BasisX = XYZ.BasisX;
                transform.BasisY = XYZ.BasisZ;
                transform.BasisZ = XYZ.BasisY;
                var section = new BoundingBoxXYZ
                {
                    Transform = transform,
                    Min = new XYZ(-halfWidth, -halfHeight, 0),
                    Max = new XYZ(halfWidth, halfHeight, depth),
                };
                view = ViewSection.CreateSection(doc, ViewFamilyTypeId(doc, ViewFamily.Section), section);
                break;
            }
            default:
                view = View3D.CreateIsometric(doc, ViewFamilyTypeId(doc, ViewFamily.ThreeDimensional));
                break;
        }
        view.Name = $"HUB export {frame.Index} {Guid.NewGuid():N}";
        view.DisplayStyle = DisplayStyle.HLR;
        return view.Id;
    }

    private static byte[] ExportPng(Document doc, ElementId viewId, ExportPlan.Frame frame, string tempDir)
    {
        var prefix = Path.Combine(tempDir, $"view_{frame.Index}");
        var options = new ImageExportOptions
        {
            ExportRange = ExportRange.SetOfViews,
            PixelSize = frame.Px,
            ZoomType = ZoomFitType.FitToPage,
            FitDirection = FitDirectionType.Horizontal,
            HLRandWFViewsFileType = ImageFileType.PNG,
            ShadowViewsFileType = ImageFileType.PNG,
            ImageResolution = ImageResolution.DPI_150,
            FilePath = prefix,
        };
        options.SetViewsAndSheets(new List<ElementId> { viewId });
        try
        {
            doc.ExportImage(options);
        }
        catch (Exception ex)
        {
            throw new OpFailure("view_export_failed", $"{frame.Name}: {ex.Message}");
        }
        // Revit appends " - <view type> - <view name>.png" to FilePath
        var file = Directory.GetFiles(tempDir, $"view_{frame.Index}*.png").OrderBy(f => f, StringComparer.Ordinal).FirstOrDefault()
            ?? throw new OpFailure("view_export_failed", $"{frame.Name}: Revit wrote no PNG");
        return File.ReadAllBytes(file);
    }
}

/// <summary>Phase 7 finish parameters (SI-4, docs/PHASE7_DESIGN.md §3.6): the id-mapped
/// element's parameter is set only when the enrolled allowlist names the param for the
/// element's category (ParamCategories from its BuiltInCategory), the parameter exists
/// (Comments via ALL_MODEL_INSTANCE_COMMENTS; the CHPT_* shared parameters must be bound
/// per docs/REVIT_TEMPLATE_CONTENT.md), is writable, and the value fits its StorageType.
/// Codes: param_not_allowlisted, unknown_param, param_readonly, param_type_mismatch,
/// param_set_failed. Nothing enters the id-map.</summary>
public sealed class SetParameterHandler : IOpHandler
{
    public string Op => "set_parameter";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<SetParameterArgs>(args);
        var allowlist = context.Catalogs.RequireParamAllowlist();
        var element = context.ResolveTarget(a.TargetId);
        var category = ParamCategories.Vocabulary(element.Category?.BuiltInCategory.ToString());
        if (!allowlist.IsAllowed(a.Param, category))
            throw new OpFailure("param_not_allowlisted",
                $"{a.Param} on {a.TargetId} ({category ?? element.Category?.Name ?? "no category"})");
        var parameter = a.Param == "Comments"
            ? element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            : element.LookupParameter(a.Param);
        if (parameter is null)
            throw new OpFailure("unknown_param",
                $"{a.Param} is not bound to {element.Category?.Name ?? "this element"} in this model — bind the shared parameter (docs/REVIT_TEMPLATE_CONTENT.md)");
        if (parameter.IsReadOnly) throw new OpFailure("param_readonly", $"{a.Param} on {a.TargetId}");
        if (allowlist.RequiresString(a.Param) && a.Value.ValueKind != JsonValueKind.String)
            throw new OpFailure("param_type_mismatch", $"{a.Param} takes a string, got {a.Value.ValueKind}");
        var decision = ParamValueCoercion.Decide(a.Value, parameter.StorageType.ToString());
        var ok = decision.Kind switch
        {
            ParamValueCoercion.Kind.SetString => parameter.Set(decision.StringValue!),
            ParamValueCoercion.Kind.SetDouble => parameter.Set(decision.DoubleValue),
            ParamValueCoercion.Kind.SetInteger => parameter.Set(decision.IntegerValue),
            _ => throw new OpFailure("param_type_mismatch", $"{a.Param}: {decision.Reason}"),
        };
        if (!ok) throw new OpFailure("param_set_failed", $"{a.Param} on {a.TargetId}");
    }
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
            new ExportViewsHandler(),
            new SetParameterHandler(),
        };
        var map = handlers.ToDictionary(h => h.Op);
        foreach (var op in OpArgsRegistry.ArgTypes.Keys)
            if (!map.ContainsKey(op)) map[op] = new NotImplementedOpHandler(op);
        return map;
    }
}
