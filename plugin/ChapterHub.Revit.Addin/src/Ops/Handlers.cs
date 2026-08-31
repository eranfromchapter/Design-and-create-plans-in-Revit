using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using ChapterHub.Core;
using ChapterHub.Core.Contracts;
using static ChapterHub.Core.UnitConversion;
using Wall = Autodesk.Revit.DB.Wall;

namespace ChapterHub.Revit.Addin.Ops;

// The op handlers the Phase 1 gate exercises live (create_level, create_wall,
// create_door, create_window, place_device). Every other registry op routes to
// NotImplementedOpHandler, which fails the envelope CLEANLY (rolled_back) instead of
// pretending — those handlers land with their phases (pipes/conduits Phase 6, exports
// Phase 2/7, etc.).

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
        // swing (L|R) + flip_facing orientation lands with the pre-Phase-6 live spike
        // (docs/MANUAL_REVIT_TEST.md) — hosted-instance flip semantics need live Revit.
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

public sealed class PlaceDeviceHandler : IOpHandler
{
    public string Op => "place_device";

    public void Execute(OpContext context, JsonElement args)
    {
        var a = ContractJson.Deserialize<PlaceDeviceArgs>(args);
        var host = Lookup.HostWall(context, a.HostWallId);
        var symbol = Lookup.SymbolByTypeName(
            context.Doc, BuiltInCategory.OST_ElectricalFixtures, a.Kind switch
            {
                "receptacle" or "gfci" => "CHPT_Receptacle_PLACEHOLDER",
                "switch" => "CHPT_Switch_PLACEHOLDER",
                _ => throw new OpFailure("invalid_args", a.Kind),
            });
        var (start, end) = Lookup.CenterlineMm(host);
        // Same face convention the sim pins (face_left) until room polygons land; the
        // pre-Phase-6 live spike upgrades this to true face-hosted placement.
        var point = Placement.Place("face_left", start, end, FtToMm(host.Width), a.Offset, a.HeightAfl);
        var level = context.Doc.GetElement(host.LevelId) as Level
            ?? throw new OpFailure("unknown_level", a.HostWallId);
        var instance = context.Doc.Create.NewFamilyInstance(
            new XYZ(MmToFt(point.X), MmToFt(point.Y), level.Elevation + MmToFt(a.HeightAfl)),
            symbol, host, level, StructuralType.NonStructural);
        context.MapCreated(a.Id, instance.Id);
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
            new PlaceDeviceHandler(),
        };
        var map = handlers.ToDictionary(h => h.Op);
        foreach (var op in OpArgsRegistry.ArgTypes.Keys)
            if (!map.ContainsKey(op)) map[op] = new NotImplementedOpHandler(op);
        return map;
    }
}
